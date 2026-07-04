from app.mission_control.service import get_board
from app.session_brief.models import SessionBrief


def get_session_brief() -> SessionBrief:
    board = get_board()

    return SessionBrief(
        completed=[
            item.title
            for item in board.items
            if item.status == "completed"
        ],
        in_progress=[
            item.title
            for item in board.items
            if item.status == "in_progress"
        ],
        next_steps=[
            item.title
            for item in board.items
            if item.status == "planned"
        ],
    )
