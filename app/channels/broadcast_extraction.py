import json
import re
from typing import Any

from app.prompt_runtime.extraction_fallback import run_llm_fallback
from app.understanding.parsers.skills import extract_skills

DETERMINISTIC_CONFIDENCE_THRESHOLD = 0.70

REQUIREMENT_SCHEMA_HINT = json.dumps(
    {
        "job_title": "string|null",
        "rate": "string|null",
        "location": "string|null",
        "skills": ["string"],
        "client": "string|null",
        "visa": "string|null",
    }
)

HOTLIST_SCHEMA_HINT = json.dumps(
    {
        "consultants": [
            {
                "name_or_initials": "string|null",
                "title": "string|null",
                "years_experience": "number|null",
                "rate": "string|null",
                "availability": "string|null",
                "skills": ["string"],
            }
        ]
    }
)

REQUIREMENT_KEY_ALIASES: dict[str, str] = {
    "title": "job_title",
    "role": "job_title",
    "position": "job_title",
    "job title": "job_title",
    "rate": "rate",
    "pay": "rate",
    "budget": "rate",
    "location": "location",
    "loc": "location",
    "skills": "skills",
    "tech": "skills",
    "technology": "skills",
    "client": "client",
    "end client": "client",
    "visa": "visa",
    "work auth": "visa",
    "authorization": "visa",
}

RATE_PATTERN = re.compile(r"\$\s?\d+[\-/]?\d*\s*(?:/|per\s*)?(?:hr|hour|day)", re.I)
YEARS_PATTERN = re.compile(r"\d+\+?\s*(?:years|yrs)", re.I)
LIST_LINE_PATTERN = re.compile(r"^(\d+[.)]|[-*•])\s+")


def _parse_key_value_broadcast(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        mapped_key = REQUIREMENT_KEY_ALIASES.get(normalized_key)

        if mapped_key and value.strip():
            if mapped_key == "skills":
                data[mapped_key] = [skill.strip() for skill in value.split(",") if skill.strip()]
            else:
                data[mapped_key] = value.strip()

    return data


def extract_broadcast_requirement(message: str) -> dict[str, Any]:
    """Deterministic first pass: parses key:value formatted broadcast text
    (e.g. "Title: Java Developer\\nRate: $70/hr\\nSkills: Java, Spring").
    Falls back to LLM when the message doesn't follow this structure.
    """
    parsed = _parse_key_value_broadcast(message)
    expected_fields = ["job_title", "rate", "location", "skills"]
    found_count = sum(1 for field in expected_fields if parsed.get(field))
    confidence = found_count / len(expected_fields) if expected_fields else 0.0

    result: dict[str, Any] = {
        "structured_data": parsed,
        "confidence": round(confidence, 2),
        "llm_fallback": None,
    }

    if confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD:
        outcome = run_llm_fallback(
            prompt_id="jf.broadcast.requirement.extract",
            variables={"broadcast_schema": REQUIREMENT_SCHEMA_HINT, "message": message},
            source="broadcast_requirement_extract",
        )
        result["llm_fallback"] = outcome

        if outcome.get("used"):
            merged = dict(parsed)
            merged.update(
                {
                    key: value
                    for key, value in outcome["extracted"].items()
                    if value not in (None, [], "")
                }
            )
            result["structured_data"] = merged
            result["confidence"] = max(confidence, 0.75)

    return result


def _parse_hotlist_line(line: str, known_skill_names: list[str]) -> dict[str, Any]:
    rate_match = RATE_PATTERN.search(line)
    years_match = YEARS_PATTERN.search(line)
    lower_line = line.lower()
    matched_skills = [name for name in known_skill_names if name.lower() in lower_line]

    return {
        "raw": line,
        "rate": rate_match.group(0) if rate_match else None,
        "years_experience_text": years_match.group(0) if years_match else None,
        "skills": matched_skills,
    }


def extract_broadcast_hotlist(message: str) -> dict[str, Any]:
    """Deterministic first pass: parses numbered/bulleted hotlist lines and
    extracts rate/experience/skill signals per line. Falls back to LLM when
    the message isn't list-shaped or lines don't carry recognizable fields.
    """
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    list_lines = [line for line in lines if LIST_LINE_PATTERN.match(line)]

    known_skill_names = [entry["name"] for entry in extract_skills(message)]
    parsed_lines = [_parse_hotlist_line(line, known_skill_names) for line in list_lines]

    well_formed_count = sum(1 for entry in parsed_lines if entry["rate"] and entry["skills"])
    confidence = (well_formed_count / len(parsed_lines)) if parsed_lines else 0.15

    result: dict[str, Any] = {
        "structured_data": {"consultants": parsed_lines},
        "confidence": round(confidence, 2),
        "llm_fallback": None,
    }

    if confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD:
        outcome = run_llm_fallback(
            prompt_id="jf.broadcast.hotlist.extract",
            variables={"hotlist_schema": HOTLIST_SCHEMA_HINT, "message": message},
            source="broadcast_hotlist_extract",
        )
        result["llm_fallback"] = outcome

        if outcome.get("used"):
            result["structured_data"] = outcome["extracted"]
            result["confidence"] = max(confidence, 0.75)

    return result
