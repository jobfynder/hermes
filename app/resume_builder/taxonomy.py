from app.resume_builder.models import (
    ResumeNormalizedSkill,
    ResumeSkillNormalizationRequest,
    ResumeSkillNormalizationResponse,
)
from app.understanding.taxonomy.normalizer import normalize_skill


def normalize_resume_skills(
    request: ResumeSkillNormalizationRequest,
) -> ResumeSkillNormalizationResponse:
    normalized_results = [
        ResumeNormalizedSkill(**normalize_skill(skill))
        for skill in request.skills
    ]

    canonical_skills: list[str] = []
    unknown_skills: list[str] = []

    for item in normalized_results:
        if item.matched:
            if item.normalized not in canonical_skills:
                canonical_skills.append(item.normalized)
        else:
            unknown_skills.append(item.input)

    if not request.skills:
        decision = "blocked"
        reasons = ["At least one skill is required for normalization."]
        risks = []
        next_actions = ["Provide one or more resume skills."]
    elif unknown_skills:
        decision = "needs_review"
        reasons = [
            "Some skills could not be matched to the current taxonomy."
        ]
        risks = [
            "Unknown skills must not be silently converted or discarded."
        ]
        next_actions = [
            "Review unknown skills and preserve the original terms."
        ]
    else:
        decision = "completed"
        reasons = [
            "All supplied skills were normalized deterministically."
        ]
        risks = []
        next_actions = [
            "Review canonical mappings before accepting resume changes."
        ]

    return ResumeSkillNormalizationResponse(
        decision=decision,
        normalized_skills=normalized_results,
        canonical_skills=canonical_skills,
        unknown_skills=unknown_skills,
        human_review_required=True,
        external_ai_used=False,
        source_traceability_present=bool(
            request.source_references
        ),
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        metadata={
            **request.metadata,
            "input_skill_count": len(request.skills),
            "matched_skill_count": sum(
                1 for item in normalized_results if item.matched
            ),
            "unknown_skill_count": len(unknown_skills),
            "source_reference_count": len(
                request.source_references
            ),
            "taxonomy_used": True,
            "prompt_runtime_used": False,
            "external_ai_used": False,
        },
    )
