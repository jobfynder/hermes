from app.resume_builder.models import (
    ResumeDocumentInput,
    ResumeQualityRequest,
    ResumeSectionInput,
    ResumeSourceReference,
)
from app.resume_builder.quality import analyze_resume_quality


def verified_reference(
    source_id: str,
    field_path: str,
) -> ResumeSourceReference:
    return ResumeSourceReference(
        source_id=source_id,
        source_type="parsed_resume",
        field_path=field_path,
        verified=True,
    )


def main() -> None:
    blocked = analyze_resume_quality(
        ResumeQualityRequest(
            document=ResumeDocumentInput()
        )
    )

    assert blocked.decision == "blocked"
    assert blocked.automatic_fix_allowed is False
    assert blocked.external_ai_used is False

    review = analyze_resume_quality(
        ResumeQualityRequest(
            document=ResumeDocumentInput(
                sections=[
                    ResumeSectionInput(
                        section_id="summary",
                        section_type="summary",
                        content="Backend engineer.",
                    ),
                    ResumeSectionInput(
                        section_id="skills",
                        section_type="skills",
                        content="Java, AWS",
                    ),
                ]
            )
        )
    )

    assert review.decision == "needs_review"
    assert "contact" in review.missing_sections
    assert "experience" in review.missing_sections
    assert "education" in review.missing_sections
    assert "summary" in review.unverified_sections
    assert review.human_review_required is True
    assert review.automatic_fix_allowed is False
    assert review.external_ai_used is False
    assert review.quality_score < 100.0

    completed = analyze_resume_quality(
        ResumeQualityRequest(
            document=ResumeDocumentInput(
                source_text="Verified resume source.",
                sections=[
                    ResumeSectionInput(
                        section_id="contact",
                        section_type="contact",
                        content="Candidate contact details",
                        source_references=[
                            verified_reference(
                                "source-contact",
                                "contact",
                            )
                        ],
                    ),
                    ResumeSectionInput(
                        section_id="summary",
                        section_type="summary",
                        content="Backend engineer.",
                        source_references=[
                            verified_reference(
                                "source-summary",
                                "summary",
                            )
                        ],
                    ),
                    ResumeSectionInput(
                        section_id="skills",
                        section_type="skills",
                        content="Java, AWS",
                        source_references=[
                            verified_reference(
                                "source-skills",
                                "skills",
                            )
                        ],
                    ),
                    ResumeSectionInput(
                        section_id="experience",
                        section_type="experience",
                        content="Built backend services.",
                        source_references=[
                            verified_reference(
                                "source-experience",
                                "experience",
                            )
                        ],
                    ),
                    ResumeSectionInput(
                        section_id="education",
                        section_type="education",
                        content="Verified education.",
                        source_references=[
                            verified_reference(
                                "source-education",
                                "education",
                            )
                        ],
                    ),
                ],
            )
        )
    )

    assert completed.decision == "completed"
    assert completed.quality_score == 100.0
    assert completed.completeness_score == 100.0
    assert completed.provenance_score == 100.0
    assert completed.missing_sections == []
    assert completed.empty_sections == []
    assert completed.unverified_sections == []
    assert completed.automatic_fix_allowed is False
    assert completed.external_ai_used is False
    assert completed.metadata["prompt_runtime_used"] is False

    print(
        "HERMES-800 resume builder quality checks passed."
    )


if __name__ == "__main__":
    main()
