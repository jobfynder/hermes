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
        "skills": ["string"],
        "years_experience": "number|null",
        "current_title": "string|null",
        "email": "string|null",
        "phone": "string|null",
        "linkedin_url": "string|null",
        "work_authorization": "string|null",
        "employers": ["string"],
        "education": ["string"],
        "certifications": ["string"],
    }
)

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
