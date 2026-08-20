from app.context.models import CandidateCardBuildRequest, CandidateCardV1
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


def build_candidate_card(request: CandidateCardBuildRequest) -> CandidateCardV1:
    """Builds a compact Candidate Card - the only form of candidate data that should
    ever reach an LLM prompt. Raw resume text is never passed through directly: if
    only source_text is supplied, it is first run through Hermes's deterministic
    resume parser, and only the resulting structured fields are used to build the card.
    """
    structured = dict(request.structured_resume)
    confidence: float | None = None

    if not structured and request.source_text:
        result = understand_document(
            RawDocument(content=request.source_text, document_kind="resume")
        )
        structured = result.structured_data
        confidence = result.quality.confidence

    skills = structured.get("normalized_skills") or structured.get("skills") or []

    summary_snippet = None
    if request.source_text:
        summary_snippet = request.source_text.strip()[:300] or None

    return CandidateCardV1(
        title=structured.get("current_title"),
        years_experience=structured.get("years_experience"),
        skills=skills,
        location=structured.get("location"),
        work_authorization=structured.get("work_authorization"),
        summary_snippet=summary_snippet,
        source_confidence=confidence,
        metadata=request.metadata,
    )
