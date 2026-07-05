from fastapi import APIRouter, Depends

from app.security.rbac import get_rbac_status, require_permission

router = APIRouter(
    prefix="/security",
    tags=["Security"],
)


@router.get("/rbac/status")
def rbac_status(user: dict = Depends(require_permission("security:read"))):
    return get_rbac_status()
