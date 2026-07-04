import json
from pathlib import Path

from app.mission_control.models import MissionBoard, MissionItem, MissionStatus

MISSION_BOARD_PATH = Path("/jobfynder-docs/mission-control/mission-board.json")


def default_board() -> MissionBoard:
    return MissionBoard(
        items=[
            MissionItem(
                id="HERMES-310-001",
                title="Create Mission Control API",
                status=MissionStatus.completed,
                stream="HERMES-310",
                notes="Mission board endpoint created.",
            ),
            MissionItem(
                id="HERMES-310-002",
                title="Add Mission Board persistence",
                status=MissionStatus.in_progress,
                stream="HERMES-310",
                notes="Mission board will persist to jobfynder-docs.",
            ),
            MissionItem(
                id="HERMES-310-003",
                title="Add Next Session Brief",
                status=MissionStatus.planned,
                stream="HERMES-310",
            ),
        ]
    )


def save_board(board: MissionBoard) -> None:
    MISSION_BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    MISSION_BOARD_PATH.write_text(
        json.dumps(board.model_dump(), indent=2),
        encoding="utf-8",
    )


def load_board() -> MissionBoard:
    if not MISSION_BOARD_PATH.exists():
        board = default_board()
        save_board(board)
        return board

    data = json.loads(MISSION_BOARD_PATH.read_text(encoding="utf-8"))
    return MissionBoard(**data)


def get_board() -> MissionBoard:
    return load_board()
