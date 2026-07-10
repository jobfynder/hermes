import json
from pathlib import Path

from app.resume_builder.adapters import (
    suggest_bullet,
    suggest_summary,
)
from app.resume_builder.models import (
    ResumeBulletSuggestionRequest,
    ResumeDocumentInput,
    ResumeQualityRequest,
    ResumeSkillNormalizationRequest,
    ResumeSummarySuggestionRequest,
    ResumeTailoringRequest,
)
from app.resume_builder.quality import analyze_resume_quality
from app.resume_builder.service import (
    analyze_resume_document,
    get_resume_builder_health,
    get_resume_builder_policy,
)
from app.resume_builder.tailoring import analyze_resume_tailoring
from app.resume_builder.taxonomy import normalize_resume_skills


FIXTURE_DIR = Path("/app/docs/hermes-800/api-fixtures")


def load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name

    if not path.exists():
        raise AssertionError(f"fixture missing: {path}")

    return json.loads(path.read_text())


def main() -> None:
    health = get_resume_builder_health()
    expected_health = load_fixture(
        "resume-builder-health-response.json"
    )
    assert health.model_dump() == expected_health

    policy = get_resume_builder_policy()
    expected_policy = load_fixture(
        "resume-builder-policy-response.json"
    )
    assert policy.model_dump() == expected_policy

    analyze_request = ResumeDocumentInput(
        **load_fixture("analyze-request.json")
    )
    analyze_result = analyze_resume_document(analyze_request)
    assert analyze_result.decision == "completed"
    assert analyze_result.human_review_required is True
    assert analyze_result.metadata["external_ai_used"] is False

    summary_request = ResumeSummarySuggestionRequest(
        **load_fixture("summary-suggest-request.json")
    )
    summary_result = suggest_summary(summary_request)
    assert summary_result.prompt_id == (
        "resume_builder.summary_improve"
    )
    assert summary_result.mode_effective == "dry_run"
    assert summary_result.human_review_required is True
    assert summary_result.metadata["external_ai_used"] is False

    bullet_request = ResumeBulletSuggestionRequest(
        **load_fixture("bullet-suggest-request.json")
    )
    bullet_result = suggest_bullet(bullet_request)
    assert bullet_result.prompt_id == (
        "resume_builder.bullet_rewrite"
    )
    assert bullet_result.mode_effective == "dry_run"
    assert bullet_result.human_review_required is True
    assert bullet_result.metadata["external_ai_used"] is False

    skills_request = ResumeSkillNormalizationRequest(
        **load_fixture("skills-normalize-request.json")
    )
    skills_result = normalize_resume_skills(skills_request)
    assert skills_result.decision == "needs_review"
    assert skills_result.external_ai_used is False
    assert "JavaScript" in skills_result.canonical_skills
    assert "React" in skills_result.canonical_skills
    assert "Kubernetes" in skills_result.canonical_skills
    assert "Unknown Internal Platform" in skills_result.unknown_skills

    tailoring_request = ResumeTailoringRequest(
        **load_fixture("tailor-request.json")
    )
    tailoring_result = analyze_resume_tailoring(
        tailoring_request
    )
    assert tailoring_result.decision == "needs_review"
    assert "Kafka" in tailoring_result.missing_required_skills
    assert tailoring_result.automatic_rewrite_allowed is False
    assert tailoring_result.external_ai_used is False

    quality_request = ResumeQualityRequest(
        **load_fixture("quality-analyze-request.json")
    )
    quality_result = analyze_resume_quality(quality_request)
    assert quality_result.decision == "completed"
    assert quality_result.quality_score == 100.0
    assert quality_result.automatic_fix_allowed is False
    assert quality_result.external_ai_used is False

    print("HERMES-800 consolidated foundation checks passed.")


if __name__ == "__main__":
    main()
