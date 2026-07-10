from app.prompt_runtime.models import PromptRunRequest
from app.prompt_runtime.service import run_prompt
from app.resume_builder.models import (
    ResumeBulletSuggestionRequest,
    ResumeSuggestionResponse,
    ResumeSummarySuggestionRequest,
)


def _build_response(
    *,
    suggestion_type: str,
    request,
    prompt_result,
) -> ResumeSuggestionResponse:
    return ResumeSuggestionResponse(
        suggestion_type=suggestion_type,
        decision=prompt_result.decision,
        prompt_id=prompt_result.prompt_id,
        prompt_version=prompt_result.prompt_version,
        mode_requested="dry_run",
        mode_effective="dry_run",
        provider=prompt_result.provider,
        output_text=prompt_result.output_text,
        human_review_required=True,
        source_traceability_present=bool(
            request.source_references
        ),
        reasons=prompt_result.reasons,
        risks=prompt_result.risks,
        next_actions=prompt_result.next_actions,
        rendered_messages=[
            {
                "role": message.role,
                "content": message.content,
            }
            for message in prompt_result.rendered_messages
        ],
        metadata={
            **request.metadata,
            "prompt_run_id": prompt_result.run_id,
            "external_ai_used": False,
            "prompt_runtime_used": True,
            "prompt_runtime_mode": "dry_run",
            "source_reference_count": len(
                request.source_references
            ),
            "human_review_required": True,
        },
    )


def suggest_summary(
    request: ResumeSummarySuggestionRequest,
) -> ResumeSuggestionResponse:
    variables = {
        "source_text": request.source_text,
    }

    if request.target_role:
        variables["target_role"] = request.target_role
    if request.tone:
        variables["tone"] = request.tone
    if request.constraints:
        variables["constraints"] = request.constraints

    result = run_prompt(
        PromptRunRequest(
            prompt_id="resume_builder.summary_improve",
            variables=variables,
            mode="dry_run",
            correlation_id=request.correlation_id,
            actor_id=request.actor_id,
            source="hermes-800-resume-builder",
            metadata={
                **request.metadata,
                "suggestion_type": "summary",
                "source_reference_count": len(
                    request.source_references
                ),
                "forced_dry_run": True,
            },
        )
    )

    return _build_response(
        suggestion_type="summary",
        request=request,
        prompt_result=result,
    )


def suggest_bullet(
    request: ResumeBulletSuggestionRequest,
) -> ResumeSuggestionResponse:
    variables = {
        "source_text": request.source_text,
    }

    if request.target_role:
        variables["target_role"] = request.target_role
    if request.skills_to_emphasize:
        variables["skills_to_emphasize"] = (
            request.skills_to_emphasize
        )
    if request.constraints:
        variables["constraints"] = request.constraints

    result = run_prompt(
        PromptRunRequest(
            prompt_id="resume_builder.bullet_rewrite",
            variables=variables,
            mode="dry_run",
            correlation_id=request.correlation_id,
            actor_id=request.actor_id,
            source="hermes-800-resume-builder",
            metadata={
                **request.metadata,
                "suggestion_type": "bullet",
                "source_reference_count": len(
                    request.source_references
                ),
                "forced_dry_run": True,
            },
        )
    )

    return _build_response(
        suggestion_type="bullet",
        request=request,
        prompt_result=result,
    )
