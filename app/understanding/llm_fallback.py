import json
from typing import Any

from app.prompt_runtime.extraction_fallback import run_llm_fallback
from app.understanding.models import DocumentKind, ExtractedText
from app.understanding.taxonomy.loader import load_skills_taxonomy

FALLBACK_PROMPT_MAP: dict[DocumentKind, str] = {
    "resume": "jf.resume.parse",
    "job_description": "jf.jobs.jd.extract",
}

RESUME_SCHEMA_HINT = json.dumps(
    {
        "name": "string|null",
        "display_name": "string|null",
        "current_title": "string|null",
        "title": "string|null",
        "summary": "string|null",
        "skills": ["string"],
        "years_experience": "number|null",
        "email": "string|null",
        "phone": "string|null",
        "linkedin_url": "string|null",
        "location": "string|null",
        "work_authorization": "string|null",
        "experience": [
            {
                "company": "string",
                "title": "string",
                "startDate": "string|null",
                "endDate": "string|null",
                "location": "string|null",
                "description": "string|null",
            }
        ],
        "education": [
            {
                "institution": "string",
                "degree": "string|null",
                "field": "string|null",
                "year": "string|null",
            }
        ],
        "certifications": ["string"],
    }
)

_LLM_FIELD_ALIASES = {
    "name": ("name", "display_name", "full_name"),
    "current_title": ("current_title", "title", "headline"),
    "phone": ("phone", "mobile"),
    "email": ("email",),
    "location": ("location",),
    "summary": ("summary", "professional_summary", "about"),
    "experience": ("experience",),
    "education": ("education",),
    "certifications": ("certifications", "certs"),
}


def merge_llm_extracted(structured_data: dict[str, Any], extracted: Any) -> None:
    """Fill empty deterministic fields from an LLM extract without overwriting."""
    if not isinstance(extracted, dict):
        return

    for field, aliases in _LLM_FIELD_ALIASES.items():
        existing = structured_data.get(field)
        if existing not in (None, "", [], {}):
            continue
        for alias in aliases:
            value = extracted.get(alias)
            if value not in (None, "", [], {}):
                structured_data[field] = value
                break

JD_SCHEMA_HINT = json.dumps(
    {
        "job_title": "string|null",
        "required_skills": ["string"],
        "preferred_skills": ["string"],
        "years_experience": "number|null",
        "location": "string|null",
        "employment_type": "string|null",
        "work_authorization": "string|null",
        "rate_or_salary": "string|null",
    }
)


def _taxonomy_subset() -> str:
    try:
        taxonomy = load_skills_taxonomy()
        names = [skill.get("name") for skill in taxonomy.get("skills", []) if skill.get("name")]
        return json.dumps(names[:60])
    except Exception:
        return "[]"


def _build_fallback_variables(document_kind: DocumentKind, extracted: ExtractedText) -> dict[str, Any]:
    if document_kind == "resume":
        return {
            "clean_resume": extracted.text,
            "resume_schema": RESUME_SCHEMA_HINT,
        }

    if document_kind == "job_description":
        return {
            "clean_jd": extracted.text,
            "job_schema": JD_SCHEMA_HINT,
            "taxonomy_subset": _taxonomy_subset(),
        }

    return {}


def apply_llm_fallback(
    document_kind: DocumentKind,
    extracted: ExtractedText,
    source: str = "understanding_service",
) -> dict[str, Any]:
    """Runs the matching Langfuse fallback prompt when deterministic parsing is weak."""
    prompt_id = FALLBACK_PROMPT_MAP.get(document_kind)

    if not prompt_id:
        return {"used": False, "prompt_id": None, "reason": "no_fallback_prompt_mapped_for_document_kind"}

    if not extracted.text.strip():
        return {"used": False, "prompt_id": prompt_id, "reason": "no_usable_text"}

    return run_llm_fallback(
        prompt_id=prompt_id,
        variables=_build_fallback_variables(document_kind, extracted),
        source=source,
    )
