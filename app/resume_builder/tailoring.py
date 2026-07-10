from app.matching.models import ResumeToJobMatchRequest
from app.matching.scorer import evaluate_resume_to_job
from app.resume_builder.models import (
    ResumeTailoringOpportunity,
    ResumeTailoringRequest,
    ResumeTailoringResponse,
)


def analyze_resume_tailoring(
    request: ResumeTailoringRequest,
) -> ResumeTailoringResponse:
    if not request.resume or not request.job:
        missing: list[str] = []

        if not request.resume:
            missing.append("resume")
        if not request.job:
            missing.append("job")

        return ResumeTailoringResponse(
            decision="blocked",
            match_decision="not_evaluated",
            match_score=0.0,
            human_review_required=True,
            automatic_rewrite_allowed=False,
            external_ai_used=False,
            source_traceability_present=bool(
                request.source_references
            ),
            reasons=[
                "Resume and job inputs are required for tailoring analysis."
            ],
            risks=[
                "Tailoring without both source documents could introduce "
                "unsupported claims."
            ],
            next_actions=[
                "Provide the missing inputs: " + ", ".join(missing) + "."
            ],
            metadata={
                **request.metadata,
                "missing_inputs": missing,
                "matching_used": False,
                "prompt_runtime_used": False,
                "external_ai_used": False,
            },
        )

    match_result = evaluate_resume_to_job(
        ResumeToJobMatchRequest(
            resume=request.resume,
            job=request.job,
        )
    )

    opportunities: list[ResumeTailoringOpportunity] = []

    for skill in match_result.matched_required_skills:
        opportunities.append(
            ResumeTailoringOpportunity(
                code="emphasize_verified_required_skill",
                category="matched_skill",
                skill=skill,
                message=(
                    f"Emphasize the verified required skill '{skill}' "
                    "where it is already supported by resume evidence."
                ),
                requires_user_input=False,
                safe_to_emphasize=True,
            )
        )

    for skill in match_result.missing_required_skills:
        opportunities.append(
            ResumeTailoringOpportunity(
                code="missing_required_skill",
                category="missing_required_skill",
                skill=skill,
                message=(
                    f"The job requires '{skill}', but it is not supported "
                    "by the supplied resume data."
                ),
                requires_user_input=True,
                safe_to_emphasize=False,
            )
        )

    for skill in match_result.matched_preferred_skills:
        opportunities.append(
            ResumeTailoringOpportunity(
                code="emphasize_verified_preferred_skill",
                category="preferred_skill",
                skill=skill,
                message=(
                    f"Consider emphasizing the verified preferred skill "
                    f"'{skill}'."
                ),
                requires_user_input=False,
                safe_to_emphasize=True,
            )
        )

    if match_result.missing_required_skills:
        decision = "needs_review"
        reasons = [
            "Tailoring opportunities were identified, but required skill "
            "gaps need human review."
        ]
        risks = list(match_result.risks) + [
            "Missing required skills must not be added unless the user "
            "provides verifiable supporting experience."
        ]
        next_actions = [
            "Ask the user to confirm whether they have evidence for each "
            "missing required skill.",
            "Emphasize only skills already supported by resume evidence.",
        ]
    else:
        decision = "completed"
        reasons = [
            "Deterministic matching identified source-supported tailoring "
            "opportunities."
        ]
        risks = list(match_result.risks)
        next_actions = [
            "Review the opportunities before requesting any rewrite.",
            "Keep every accepted change grounded in supplied resume evidence.",
        ]

    return ResumeTailoringResponse(
        decision=decision,
        match_decision=match_result.decision,
        match_score=match_result.match_score,
        matched_required_skills=match_result.matched_required_skills,
        missing_required_skills=match_result.missing_required_skills,
        matched_preferred_skills=match_result.matched_preferred_skills,
        opportunities=opportunities,
        human_review_required=True,
        automatic_rewrite_allowed=False,
        external_ai_used=False,
        source_traceability_present=bool(
            request.source_references
        ),
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        metadata={
            **request.metadata,
            "matching_used": True,
            "matching_policy_snapshot": match_result.policy_snapshot,
            "matching_reasons": match_result.reasons,
            "prompt_runtime_used": False,
            "external_ai_used": False,
            "source_reference_count": len(
                request.source_references
            ),
        },
    )
