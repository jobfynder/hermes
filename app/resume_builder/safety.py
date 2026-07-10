from app.resume_builder.models import (
    ResumeBuilderResult,
    ResumeDocumentInput,
    ResumeIssue,
)


SUPPORTED_SOURCE_TYPES = {
    "resume_text",
    "parsed_resume",
    "verified_profile",
    "user_input",
}


def evaluate_resume_document(
    document: ResumeDocumentInput,
) -> ResumeBuilderResult:
    issues: list[ResumeIssue] = []
    reasons: list[str] = []
    risks: list[str] = []
    next_actions: list[str] = []

    has_source_text = bool(
        document.source_text and document.source_text.strip()
    )
    has_sections = bool(document.sections)

    if not has_source_text and not has_sections:
        issues.append(
            ResumeIssue(
                code="resume_content_required",
                severity="error",
                message=(
                    "Provide resume source text or at least one "
                    "structured resume section."
                ),
                requires_user_input=True,
            )
        )

    seen_section_ids: set[str] = set()

    for section in document.sections:
        if section.section_id in seen_section_ids:
            issues.append(
                ResumeIssue(
                    code="duplicate_section_id",
                    severity="error",
                    message=(
                        f"Duplicate section ID: {section.section_id}"
                    ),
                    section_id=section.section_id,
                )
            )
        seen_section_ids.add(section.section_id)

        if not section.content.strip():
            issues.append(
                ResumeIssue(
                    code="empty_section_content",
                    severity="warning",
                    message="Resume section content is empty.",
                    section_id=section.section_id,
                    requires_user_input=True,
                )
            )

        if not section.source_references:
            issues.append(
                ResumeIssue(
                    code="source_traceability_missing",
                    severity="warning",
                    message=(
                        "Section has no source reference. Suggestions "
                        "must not introduce unsupported facts."
                    ),
                    section_id=section.section_id,
                    requires_user_input=True,
                )
            )

        for reference in section.source_references:
            if reference.source_type not in SUPPORTED_SOURCE_TYPES:
                issues.append(
                    ResumeIssue(
                        code="unsupported_source_type",
                        severity="error",
                        message=(
                            "Unsupported source type: "
                            f"{reference.source_type}"
                        ),
                        section_id=section.section_id,
                    )
                )

    error_count = sum(
        1 for issue in issues if issue.severity == "error"
    )
    warning_count = sum(
        1 for issue in issues if issue.severity == "warning"
    )

    if error_count:
        decision = "blocked"
        reasons.append(
            "Resume input failed deterministic safety validation."
        )
        risks.append(
            "Generating suggestions from invalid input could create "
            "unsupported resume content."
        )
        next_actions.append(
            "Correct all validation errors and resubmit."
        )
    elif warning_count:
        decision = "needs_review"
        reasons.append(
            "Resume input is usable but requires human review."
        )
        risks.append(
            "Missing provenance may make some suggestions unsafe."
        )
        next_actions.append(
            "Confirm missing source information before accepting changes."
        )
    else:
        decision = "completed"
        reasons.append(
            "Resume input passed deterministic safety validation."
        )
        next_actions.append(
            "Proceed only with human-reviewed, source-grounded suggestions."
        )

    return ResumeBuilderResult(
        decision=decision,
        human_review_required=True,
        issues=issues,
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        metadata={
            "section_count": len(document.sections),
            "error_count": error_count,
            "warning_count": warning_count,
            "external_ai_used": False,
            "prompt_runtime_used": False,
        },
    )
