import re
from typing import Any

from app.understanding.models import DocumentKind, ExtractedText
from app.understanding.parsers.skills import extract_skills


def extract_years_experience(text: str) -> int | None:
    patterns = [
        r"(\d{1,2})\+?\s*(?:years|yrs)\s*(?:of\s*)?(?:experience|exp)?",
        r"experience\s*(?:of\s*)?(\d{1,2})\+?\s*(?:years|yrs)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def parse_basic_structured_data(
    extracted: ExtractedText,
    document_kind: DocumentKind = "unknown",
) -> dict[str, Any]:
    text = extracted.text or ""

    return {
        "document_kind": document_kind,
        "skills": extract_skills(text),
        "years_experience": extract_years_experience(text),
        "parser": {
            "name": "basic_local_parser",
            "uses_llm": False,
        },
    }
