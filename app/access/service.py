from app.access.models import ActionAccessDecision, ActionAccessRequest
from app.access.registry import allowed_actions_for, is_action_allowed
from app.runtime.events import emit_event
from app.runtime.intake_log import record_intake


def authorize_action(request: ActionAccessRequest) -> ActionAccessDecision:
    allowed_actions = allowed_actions_for(request.role)

    if is_action_allowed(request.role, request.action):
        decision = ActionAccessDecision(
            status="allowed",
            actor_id=request.actor_id,
            role=request.role,
            action=request.action,
            channel=request.channel,
            reason=None,
            allowed_actions=allowed_actions,
        )
    else:
        decision = ActionAccessDecision(
            status="denied",
            actor_id=request.actor_id,
            role=request.role,
            action=request.action,
            channel=request.channel,
            reason="action_not_allowed_for_role",
            allowed_actions=allowed_actions,
        )

    record_intake(
        {
            "status": "action_access_checked",
            "actor_id": request.actor_id,
            "role": request.role,
            "action": request.action,
            "channel": request.channel,
            "decision": decision.status,
            "reason": decision.reason,
        }
    )

    emit_event(
        "access.action_checked",
        {
            "actor_id": request.actor_id,
            "role": request.role,
            "action": request.action,
            "channel": request.channel,
            "decision": decision.status,
            "reason": decision.reason,
        },
    )

    return decision
