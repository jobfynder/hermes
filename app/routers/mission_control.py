from fastapi import APIRouter, Depends

from app.mission_control.service import get_board
from app.security.rbac import require_permission

router = APIRouter(
    prefix="/mission-control",
    tags=["Mission Control"],
)


@router.get("")
def mission_board(user: dict = Depends(require_permission("mission_control:read"))):
    return get_board()
