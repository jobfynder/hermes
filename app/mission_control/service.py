from app.mission_control.models import MissionBoard, MissionItem, MissionStatus

MISSION_BOARD = MissionBoard(
    items=[
        MissionItem(
            id="HERMES-310-001",
            title="Create Mission Control API",
            status=MissionStatus.in_progress,
            stream="HERMES-310",
            notes="Mission board endpoint created.",
        ),
        MissionItem(
            id="HERMES-310-002",
            title="Add Mission Board persistence",
            status=MissionStatus.planned,
            stream="HERMES-310",
        ),
        MissionItem(
            id="HERMES-310-003",
            title="Add Next Session Brief",
            status=MissionStatus.planned,
            stream="HERMES-310",
        ),
    ]
)


def get_board() -> MissionBoard:
    return MISSION_BOARD
