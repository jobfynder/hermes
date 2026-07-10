from app.resume_builder.models import (
    ResumeSourceReference,
    ResumeTailoringRequest,
)
from app.resume_builder.tailoring import analyze_resume_tailoring


def main() -> None:
    blocked = analyze_resume_tailoring(
        ResumeTailoringRequest()
    )

    assert blocked.decision == "blocked"
    assert blocked.match_decision == "not_evaluated"
    assert blocked.match_score == 0.0
    assert blocked.automatic_rewrite_allowed is False
    assert blocked.external_ai_used is False

    review = analyze_resume_tailoring(
        ResumeTailoringRequest(
            resume={
                "skills": [
                    "Java",
                    "Spring Boot",
                    "PostgreSQL",
                    "AWS",
                ],
                "years_experience": 7,
                "location": "Dallas, TX",
                "work_authorization": "H1B",
            },
            job={
                "required_skills": [
                    "Java",
                    "Spring Boot",
                    "Kafka",
                ],
                "preferred_skills": [
                    "AWS",
                    "Docker",
                ],
                "years_experience": 6,
                "location": "Dallas, TX",
                "work_authorization": "H1B",
            },
            source_references=[
                ResumeSourceReference(
                    source_id="resume-source-1",
                    source_type="parsed_resume",
                    field_path="skills",
                    verified=True,
                )
            ],
        )
    )

    assert review.decision == "needs_review"
    assert "Java" in review.matched_required_skills
    assert "Spring Boot" in review.matched_required_skills
    assert "Kafka" in review.missing_required_skills
    assert "AWS" in review.matched_preferred_skills
    assert review.human_review_required is True
    assert review.automatic_rewrite_allowed is False
    assert review.external_ai_used is False
    assert review.source_traceability_present is True
    assert review.metadata["matching_used"] is True
    assert review.metadata["prompt_runtime_used"] is False
    assert any(
        item.skill == "Kafka"
        and item.requires_user_input is True
        and item.safe_to_emphasize is False
        for item in review.opportunities
    )

    completed = analyze_resume_tailoring(
        ResumeTailoringRequest(
            resume={
                "skills": [
                    "Java",
                    "Spring Boot",
                    "Kafka",
                    "AWS",
                ],
                "years_experience": 7,
                "location": "Dallas, TX",
                "work_authorization": "H1B",
            },
            job={
                "required_skills": [
                    "Java",
                    "Spring Boot",
                    "Kafka",
                ],
                "preferred_skills": [
                    "AWS",
                ],
                "years_experience": 6,
                "location": "Dallas, TX",
                "work_authorization": "H1B",
            },
        )
    )

    assert completed.decision == "completed"
    assert completed.missing_required_skills == []
    assert completed.automatic_rewrite_allowed is False
    assert completed.external_ai_used is False

    print(
        "HERMES-800 resume builder tailoring checks passed."
    )


if __name__ == "__main__":
    main()
