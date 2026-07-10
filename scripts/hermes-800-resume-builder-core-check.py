from app.resume_builder.models import (
    ResumeDocumentInput,
    ResumeSectionInput,
    ResumeSourceReference,
)
from app.resume_builder.service import (
    analyze_resume_document,
    get_resume_builder_health,
    get_resume_builder_policy,
)


def main() -> None:
    health = get_resume_builder_health()
    assert health.status == "healthy"
    assert health.external_ai_enabled is False
    assert health.prompt_runtime_default_mode == "dry_run"
    assert health.human_review_required is True

    policy = get_resume_builder_policy()
    assert policy.fabrication_allowed is False
    assert policy.external_ai_enabled is False
    assert policy.automatic_publish_allowed is False
    assert policy.human_review_required is True

    empty_result = analyze_resume_document(
        ResumeDocumentInput()
    )
    assert empty_result.decision == "blocked"
    assert any(
        issue.code == "resume_content_required"
        for issue in empty_result.issues
    )

    review_result = analyze_resume_document(
        ResumeDocumentInput(
            sections=[
                ResumeSectionInput(
                    section_id="summary",
                    section_type="summary",
                    content="Experienced software engineer.",
                )
            ]
        )
    )
    assert review_result.decision == "needs_review"
    assert any(
        issue.code == "source_traceability_missing"
        for issue in review_result.issues
    )

    safe_result = analyze_resume_document(
        ResumeDocumentInput(
            source_text="Experienced software engineer.",
            sections=[
                ResumeSectionInput(
                    section_id="summary",
                    section_type="summary",
                    content="Experienced software engineer.",
                    source_references=[
                        ResumeSourceReference(
                            source_id="resume-source-1",
                            source_type="resume_text",
                            field_path="summary",
                            excerpt=(
                                "Experienced software engineer."
                            ),
                            verified=True,
                        )
                    ],
                )
            ],
        )
    )
    assert safe_result.decision == "completed"
    assert safe_result.human_review_required is True
    assert safe_result.metadata["external_ai_used"] is False
    assert safe_result.metadata["prompt_runtime_used"] is False

    print(
        "HERMES-800 resume builder core checks passed."
    )


if __name__ == "__main__":
    main()
