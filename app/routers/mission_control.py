from fastapi import APIRouter

from app.mission_control.service import get_board

router = APIRouter(
    prefix="/mission-control",
    tags=["Mission Control"],
)


@router.get("")
def mission_board():
    return get_board()
