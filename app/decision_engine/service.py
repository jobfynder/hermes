from app.action_engine.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    ActionType,
)
from app.decision_engine.models import DecisionItem


def decision_to_action(decision: DecisionItem) -> ActionItem:
    return ActionItem(
        id=decision.id,
        title=decision.title,
        action_type=ActionType(decision.decision_type.value),
        priority=ActionPriority(decision.priority.value),
        status=ActionStatus.planned,
        stream=decision.stream,
        owner="Hermes",
        notes=decision.notes,
    )
