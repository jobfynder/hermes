from app.resume_builder.models import (
    ResumeQualityMetric,
    ResumeQualityRequest,
    ResumeQualityResponse,
)


def _percentage(passed: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round((passed / total) * 100.0, 2)


def analyze_resume_quality(
    request: ResumeQualityRequest,
) -> ResumeQualityResponse:
    document = request.document
    metrics: list[ResumeQualityMetric] = []

    section_types = {
        section.section_type
        for section in document.sections
    }

    missing_sections = [
        section_type
        for section_type in request.required_sections
        if section_type not in section_types
    ]

    empty_sections = [
        section.section_id
        for section in document.sections
        if not section.content.strip()
    ]

    unverified_sections = [
        section.section_id
        for section in document.sections
        if not section.source_references
        or not any(
            reference.verified
            for reference in section.source_references
        )
    ]

    required_count = len(request.required_sections)
    present_required_count = (
        required_count - len(missing_sections)
    )

    completeness_score = _percentage(
        present_required_count,
        required_count,
    )

    non_empty_count = (
        len(document.sections) - len(empty_sections)
    )
    content_score = _percentage(
        non_empty_count,
        len(document.sections),
    )

    verified_count = (
        len(document.sections) - len(unverified_sections)
    )
    provenance_score = _percentage(
        verified_count,
        len(document.sections),
    )

    quality_score = round(
        (
            completeness_score * 0.45
            + content_score * 0.30
            + provenance_score * 0.25
        ),
        2,
    )

    metrics.append(
        ResumeQualityMetric(
            code="required_section_completeness",
            label="Required section completeness",
            score=completeness_score,
            status=(
                "pass"
                if completeness_score == 100.0
                else "fail"
            ),
            message=(
                "All required resume sections are present."
                if not missing_sections
                else "Required resume sections are missing."
            ),
            requires_user_input=bool(missing_sections),
            metadata={
                "missing_sections": missing_sections,
            },
        )
    )

    metrics.append(
        ResumeQualityMetric(
            code="section_content_quality",
            label="Section content quality",
            score=content_score,
            status=(
                "pass"
                if content_score == 100.0
                else "warning"
            ),
            message=(
                "All supplied resume sections contain content."
                if not empty_sections
                else "One or more resume sections are empty."
            ),
            requires_user_input=bool(empty_sections),
            metadata={
                "empty_sections": empty_sections,
            },
        )
    )

    metrics.append(
        ResumeQualityMetric(
            code="source_provenance_quality",
            label="Source provenance quality",
            score=provenance_score,
            status=(
                "pass"
                if provenance_score == 100.0
                else "warning"
            ),
            message=(
                "All supplied resume sections have verified provenance."
                if not unverified_sections
                else "Some resume sections lack verified provenance."
            ),
            requires_user_input=bool(unverified_sections),
            metadata={
                "unverified_sections": unverified_sections,
            },
        )
    )

    if not document.sections and not document.source_text:
        decision = "blocked"
        reasons = [
            "Resume content is required for quality analysis."
        ]
        risks = [
            "Quality analysis cannot be trusted without resume input."
        ]
        next_actions = [
            "Provide resume source text or structured sections."
        ]
    elif missing_sections or empty_sections or unverified_sections:
        decision = "needs_review"
        reasons = [
            "Resume quality issues require human review."
        ]
        risks = [
            "Missing or unverified content must not be automatically filled."
        ]
        next_actions = [
            "Provide missing sections and confirm source evidence.",
            "Review all warnings before accepting resume changes.",
        ]
    else:
        decision = "completed"
        reasons = [
            "Resume passed deterministic completeness and quality checks."
        ]
        risks = []
        next_actions = [
            "Continue with human-reviewed resume improvements only."
        ]

    return ResumeQualityResponse(
        decision=decision,
        quality_score=quality_score,
        completeness_score=completeness_score,
        provenance_score=provenance_score,
        metrics=metrics,
        missing_sections=missing_sections,
        empty_sections=empty_sections,
        unverified_sections=unverified_sections,
        human_review_required=True,
        automatic_fix_allowed=False,
        external_ai_used=False,
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        metadata={
            **request.metadata,
            "section_count": len(document.sections),
            "required_section_count": required_count,
            "matching_used": False,
            "taxonomy_used": False,
            "prompt_runtime_used": False,
            "external_ai_used": False,
        },
    )
