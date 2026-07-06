from typing import Any

from pydantic import BaseModel, Field

from app.understanding.models import DocumentKind, ParseQuality


class ParserValidation(BaseModel):
    is_valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def validate_structured_output(
    document_kind: DocumentKind,
    structured_data: dict[str, Any],
    quality: ParseQuality,
) -> ParserValidation:
    errors: list[str] = []
    warnings: list[str] = []

    structured_kind = structured_data.get("document_kind")

    if document_kind in {"resume", "job_description", "message"}:
        if structured_kind != document_kind:
            errors.append("structured_document_kind_mismatch")

    if quality.needs_fallback:
        warnings.append("extraction_quality_requires_fallback")

    skills = structured_data.get("skills") or []

    if document_kind in {"resume", "job_description"} and not skills:
        warnings.append("no_skills_extracted")

    if document_kind == "resume":
        if not structured_data.get("email") and not structured_data.get("phone"):
            warnings.append("resume_contact_not_found")

    if document_kind == "job_description":
        if not structured_data.get("job_title"):
            warnings.append("job_title_not_found")

    return ParserValidation(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        metadata={
            "validated_document_kind": document_kind,
            "structured_document_kind": structured_kind,
            "skill_count": len(skills),
            "quality_confidence": quality.confidence,
        },
    )
