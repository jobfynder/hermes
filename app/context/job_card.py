from app.context.models import JobCardBuildRequest, JobCardV1
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


def build_job_card(request: JobCardBuildRequest) -> JobCardV1:
    """Builds a compact Job Card - the only form of job data that should ever reach
    an LLM prompt. Raw JD text is never passed through directly: if only source_text
    is supplied, it is first run through Hermes's deterministic JD parser, and only
    the resulting structured fields are used to build the card.
    """
    structured = dict(request.structured_job)
    confidence: float | None = None

    if not structured and request.source_text:
        result = understand_document(
            RawDocument(content=request.source_text, document_kind="job_description")
        )
        structured = result.structured_data
        confidence = result.quality.confidence

    required_skills = structured.get("normalized_skills") or structured.get("required_skills") or []

    summary_snippet = None
    if request.source_text:
        summary_snippet = request.source_text.strip()[:300] or None

    return JobCardV1(
        title=structured.get("job_title"),
        required_skills=required_skills,
        preferred_skills=structured.get("preferred_skills") or [],
        years_experience=structured.get("years_experience"),
        location=structured.get("location"),
        employment_type=structured.get("employment_type"),
        work_authorization=structured.get("work_authorization"),
        rate_or_salary=structured.get("rate_or_salary"),
        summary_snippet=summary_snippet,
        source_confidence=confidence,
        metadata=request.metadata,
    )
