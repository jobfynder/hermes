from fastapi import APIRouter, Depends

from app.workspace.service import get_workspace
from app.security.rbac import require_permission

router = APIRouter(
    prefix="/workspace",
    tags=["Workspace"],
)


@router.get("")
def workspace(user: dict = Depends(require_permission("workspace:read"))):
    return get_workspace()
