from app.action_engine.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    ActionType,
)
from app.action_engine.service import create_action
from app.decision_engine.models import (
    DecisionItem,
    DecisionPriority,
    DecisionStatus,
    DecisionType,
)


def detect_decision(text: str) -> DecisionItem:
    return DecisionItem(
        id="AUTO-001",
        title=text.strip(),
        decision_type=DecisionType.task,
        priority=DecisionPriority.medium,
        status=DecisionStatus.detected,
        source="conversation",
    )


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


def process_decision(text: str) -> ActionItem:
    decision = detect_decision(text)
    action = decision_to_action(decision)
    return create_action(action)
