from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4
import re

router = APIRouter()

HERMES_VERSION = "0.2.0"


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


def build_response(intent: str, confidence: float, route: str, data: dict):
    return {
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


@router.post("/v1/jobs/parse")
def parse_job(request: JobParseRequest):
    return build_response(
        intent="JOB",
        confidence=1.0,
        route="job_parser",
        data={
            "job": parse_job_text(request.text),
        },
    )