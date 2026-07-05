from fastapi import APIRouter, Depends

from app.session_brief.service import get_session_brief
from app.security.rbac import require_permission

router = APIRouter(
    prefix="/session-brief",
    tags=["Session Brief"],
)


@router.get("")
def session_brief(user: dict = Depends(require_permission("session_brief:read"))):
    return get_session_brief()
