from app.resume_builder.models import (
    ResumeSkillNormalizationRequest,
    ResumeSourceReference,
)
from app.resume_builder.taxonomy import normalize_resume_skills


def main() -> None:
    empty = normalize_resume_skills(
        ResumeSkillNormalizationRequest()
    )

    assert empty.decision == "blocked"
    assert empty.normalized_skills == []
    assert empty.external_ai_used is False

    normalized = normalize_resume_skills(
        ResumeSkillNormalizationRequest(
            skills=[
                "JS",
                "ReactJS",
                "K8s",
                "Unknown Internal Platform",
            ],
            source_references=[
                ResumeSourceReference(
                    source_id="resume-source-1",
                    source_type="resume_text",
                    field_path="skills",
                    excerpt="JS, ReactJS, K8s",
                    verified=True,
                )
            ],
        )
    )

    assert normalized.decision == "needs_review"
    assert normalized.human_review_required is True
    assert normalized.external_ai_used is False
    assert normalized.source_traceability_present is True

    mappings = {
        item.input: item.normalized
        for item in normalized.normalized_skills
    }

    assert mappings["JS"] == "JavaScript"
    assert mappings["ReactJS"] == "React"
    assert mappings["K8s"] == "Kubernetes"

    assert "Unknown Internal Platform" in normalized.unknown_skills
    assert "JavaScript" in normalized.canonical_skills
    assert "React" in normalized.canonical_skills
    assert "Kubernetes" in normalized.canonical_skills

    assert normalized.metadata["prompt_runtime_used"] is False
    assert normalized.metadata["external_ai_used"] is False
    assert normalized.metadata["taxonomy_used"] is True

    safe = normalize_resume_skills(
        ResumeSkillNormalizationRequest(
            skills=["JavaScript", "AWS"]
        )
    )

    assert safe.decision == "completed"
    assert safe.unknown_skills == []

    print(
        "HERMES-800 resume builder taxonomy checks passed."
    )


if __name__ == "__main__":
    main()
