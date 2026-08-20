from fastapi import APIRouter, Depends

from app.config import HERMES_VERSION
from app.security.rbac import require_permission
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4
import re

from app.understanding.llm_fallback import apply_llm_fallback
from app.understanding.models import ExtractedText

router = APIRouter()


JOB_PARSE_CONFIDENCE_THRESHOLD = 0.6


class JobParseRequest(BaseModel):
    text: str


KNOWN_SKILLS = [
    "Java",
    "Spring Boot",
    "AWS",
    "REST API",
    "Python",
    "React",
    "Node.js",
    "PostgreSQL",
    "Docker",
    "Kubernetes",
    "TypeScript",
    "Angular",
    "Azure",
    "GCP",
    "SQL",
    "MongoDB",
]


def build_response(intent: str, confidence: float, route: str, data: dict, fallback: dict | None = None):
    response = {
        "success": True,
        "request": {
            "id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "analysis": {
            "intent": intent,
            "confidence": confidence,
            "route": route,
        },
        "data": data,
        "metadata": {
            "version": HERMES_VERSION,
        },
    }

    if fallback is not None:
        response["fallback"] = fallback

    return response


def extract_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]

    if len(first_line) <= 80:
        return first_line

    match = re.search(
        r"(Senior|Lead|Junior)?\s?[\w\s]+(Developer|Engineer|Architect|Analyst|Consultant)",
        text,
        re.I,
    )

    if match:
        return match.group(0).strip()

    return "Unknown"


def extract_skills(text: str) -> list[str]:
    found = []
    lower_text = text.lower()

    for skill in KNOWN_SKILLS:
        if skill.lower() in lower_text:
            found.append(skill)

    return found


def extract_location(text: str):
    match = re.search(
        r"Location[:\-]?\s*([A-Za-z\s]+,\s*[A-Z]{2})",
        text,
        re.I,
    )

    if match:
        return match.group(1).strip()

    return None


def extract_employment_type(text: str):
    lower_text = text.lower()

    if "contract" in lower_text:
        return "Contract"

    if "full-time" in lower_text or "full time" in lower_text:
        return "Full-time"

    if "part-time" in lower_text or "part time" in lower_text:
        return "Part-time"

    return None


def parse_job_text(text: str):
    cleaned_text = text.strip()

    return {
        "title": extract_title(cleaned_text),
        "summary": cleaned_text[:300],
        "skills": extract_skills(cleaned_text),
        "location": extract_location(cleaned_text),
        "employment_type": extract_employment_type(cleaned_text),
    }


def score_job_parse_confidence(text: str, parsed: dict) -> tuple[float, list[str]]:
    reasons = []
    score = 1.0

    if len(text.strip()) < 20:
        score -= 0.35
        reasons.append("text_too_short")

    if not parsed.get("title") or parsed["title"] == "Unknown":
        score -= 0.30
        reasons.append("title_not_found")

    if not parsed.get("skills"):
        score -= 0.20
        reasons.append("no_skills_found")

    if not parsed.get("location"):
        score -= 0.10
        reasons.append("location_not_found")

    if not parsed.get("employment_type"):
        score -= 0.05
        reasons.append("employment_type_not_found")

    return max(0.0, round(score, 2)), reasons


def _merge_fallback_fields(parsed: dict, llm_extracted: dict) -> dict:
    merged = dict(parsed)

    if (not merged.get("title") or merged["title"] == "Unknown") and llm_extracted.get("job_title"):
        merged["title"] = llm_extracted["job_title"]

    if not merged.get("skills") and llm_extracted.get("required_skills"):
        merged["skills"] = llm_extracted["required_skills"]

    if not merged.get("location") and llm_extracted.get("location"):
        merged["location"] = llm_extracted["location"]

    if not merged.get("employment_type") and llm_extracted.get("employment_type"):
        merged["employment_type"] = llm_extracted["employment_type"]

    merged["required_skills"] = llm_extracted.get("required_skills") or merged.get("skills", [])
    merged["preferred_skills"] = llm_extracted.get("preferred_skills") or []
    merged["work_authorization"] = llm_extracted.get("work_authorization")
    merged["rate_or_salary"] = llm_extracted.get("rate_or_salary")

    return merged


@router.post("/v1/jobs/parse")
def parse_job(request: JobParseRequest, user: dict = Depends(require_permission("jobs:parse"))):
    cleaned_text = request.text.strip()
    parsed = parse_job_text(cleaned_text)
    confidence, reasons = score_job_parse_confidence(cleaned_text, parsed)

    fallback_info: dict = {"action": "none", "should_call_llm": False, "llm_fallback": None}

    if confidence < JOB_PARSE_CONFIDENCE_THRESHOLD:
        fallback_info["action"] = "llm_structuring_candidate"
        fallback_info["should_call_llm"] = True
        fallback_info["reasons"] = reasons

        llm_outcome = apply_llm_fallback(
            document_kind="job_description",
            extracted=ExtractedText(text=cleaned_text, source="plain_text"),
            source="v1_jobs_parse",
        )
        fallback_info["llm_fallback"] = llm_outcome

        if llm_outcome.get("used"):
            parsed = _merge_fallback_fields(parsed, llm_outcome["extracted"])
            confidence = max(confidence, 0.75)

    return build_response(
        intent="JOB",
        confidence=confidence,
        route="job_parser",
        data={"job": parsed},
        fallback=fallback_info,
    )
