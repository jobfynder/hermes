from app.action_engine.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    ActionType,
)


def default_actions() -> list[ActionItem]:
    return [
        ActionItem(
            id="HERMES-401-001",
            title="Build Action Capture Engine",
            action_type=ActionType.feature,
            priority=ActionPriority.critical,
            status=ActionStatus.in_progress,
            owner="Pavan",
            notes="Current implementation.",
        ),
        ActionItem(
            id="HERMES-401-002",
            title="Integrate Action Engine with Workspace",
            action_type=ActionType.task,
            priority=ActionPriority.high,
            status=ActionStatus.planned,
            owner="Hermes",
        ),
    ]
