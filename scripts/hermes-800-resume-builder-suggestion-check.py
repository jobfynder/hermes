from app.resume_builder.adapters import (
    suggest_bullet,
    suggest_summary,
)
from app.resume_builder.models import (
    ResumeBulletSuggestionRequest,
    ResumeSourceReference,
    ResumeSummarySuggestionRequest,
)


def main() -> None:
    reference = ResumeSourceReference(
        source_id="resume-source-1",
        source_type="resume_text",
        field_path="summary",
        excerpt="Senior Java engineer with AWS experience.",
        verified=True,
    )

    summary = suggest_summary(
        ResumeSummarySuggestionRequest(
            source_text=(
                "Senior Java engineer with AWS experience."
            ),
            target_role="Senior Backend Engineer",
            tone="professional",
            constraints="Do not invent metrics or employers.",
            source_references=[reference],
        )
    )

    assert summary.prompt_id == (
        "resume_builder.summary_improve"
    )
    assert summary.mode_requested == "dry_run"
    assert summary.mode_effective == "dry_run"
    assert summary.human_review_required is True
    assert summary.source_traceability_present is True
    assert summary.metadata["external_ai_used"] is False
    assert summary.metadata["prompt_runtime_used"] is True

    bullet = suggest_bullet(
        ResumeBulletSuggestionRequest(
            source_text=(
                "Built Java APIs and deployed services on AWS."
            ),
            target_role="Senior Backend Engineer",
            skills_to_emphasize=[
                "Java",
                "AWS",
            ],
            constraints="Do not invent metrics.",
            source_references=[reference],
        )
    )

    assert bullet.prompt_id == (
        "resume_builder.bullet_rewrite"
    )
    assert bullet.mode_requested == "dry_run"
    assert bullet.mode_effective == "dry_run"
    assert bullet.human_review_required is True
    assert bullet.source_traceability_present is True
    assert bullet.metadata["external_ai_used"] is False
    assert bullet.metadata["prompt_runtime_used"] is True

    print(
        "HERMES-800 resume builder suggestion checks passed."
    )


if __name__ == "__main__":
    main()
