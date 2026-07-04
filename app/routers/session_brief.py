from fastapi import APIRouter

from app.session_brief.service import get_session_brief

router = APIRouter(
    prefix="/session-brief",
    tags=["Session Brief"],
)


@router.get("")
def session_brief():
    return get_session_brief()
