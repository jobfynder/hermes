from app.workspace.service import get_workspace
from app.session_brief.models import SessionBrief


def get_session_brief() -> SessionBrief:
    workspace = get_workspace()

    tasks = [
        item
        for item in workspace.items
        if item.item_type == "task"
    ]

    return SessionBrief(
        completed=[
            item.title
            for item in tasks
            if item.status == "completed"
        ],
        in_progress=[
            item.title
            for item in tasks
            if item.status == "in_progress"
        ],
        next_steps=[
            item.title
            for item in tasks
            if item.status == "planned"
        ],
    )
