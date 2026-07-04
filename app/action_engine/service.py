from app.action_engine.models import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    ActionType,
)
from app.workspace.models import WorkspaceItem
from app.workspace.service import get_workspace, save_workspace


def action_to_workspace_item(action: ActionItem) -> WorkspaceItem:
    return WorkspaceItem(
        id=action.id,
        item_type=action.action_type.value,
        title=action.title,
        status=action.status.value,
        stream=action.stream,
        notes=action.notes,
    )


def workspace_item_to_action(item: WorkspaceItem) -> ActionItem:
    return ActionItem(
        id=item.id,
        title=item.title,
        action_type=ActionType(item.item_type),
        priority=ActionPriority.medium,
        status=ActionStatus(item.status),
        stream=item.stream,
        owner="Hermes",
        notes=item.notes,
    )


def list_actions() -> list[ActionItem]:
    workspace = get_workspace()

    return [
        workspace_item_to_action(item)
        for item in workspace.items
        if item.item_type in [action_type.value for action_type in ActionType]
    ]


def get_action(action_id: str) -> ActionItem | None:
    for action in list_actions():
        if action.id == action_id:
            return action

    return None


def create_action(action: ActionItem) -> ActionItem:
    workspace = get_workspace()

    existing = get_action(action.id)
    if existing:
        raise ValueError(f"Action already exists: {action.id}")

    workspace.items.append(action_to_workspace_item(action))
    save_workspace(workspace)

    return action


def update_action(action_id: str, updated_action: ActionItem) -> ActionItem:
    workspace = get_workspace()

    for index, item in enumerate(workspace.items):
        if item.id == action_id:
            updated_action.id = action_id
            workspace.items[index] = action_to_workspace_item(updated_action)
            save_workspace(workspace)
            return updated_action

    raise KeyError(f"Action not found: {action_id}")


def delete_action(action_id: str) -> bool:
    workspace = get_workspace()

    original_count = len(workspace.items)
    workspace.items = [
        item
        for item in workspace.items
        if item.id != action_id
    ]

    if len(workspace.items) == original_count:
        return False

    save_workspace(workspace)
    return True
