from app.mission_control.models import MissionBoard, MissionItem
from app.workspace.service import get_workspace


def get_board() -> MissionBoard:
    workspace = get_workspace()

    items = [
        MissionItem(
            id=item.id,
            title=item.title,
            status=item.status,
            stream=item.stream,
            notes=item.notes,
        )
        for item in workspace.items
        if item.item_type == "task"
    ]

    return MissionBoard(items=items)
