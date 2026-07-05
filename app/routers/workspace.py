from fastapi import APIRouter

from app.workspace.service import get_workspace

router = APIRouter(
    prefix="/workspace",
    tags=["Workspace"],
)


@router.get("")
def workspace():
    return get_workspace()
