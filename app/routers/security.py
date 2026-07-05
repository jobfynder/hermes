from fastapi import APIRouter

from app.security.rbac import get_rbac_status

router = APIRouter(
    prefix="/security",
    tags=["Security"],
)


@router.get("/rbac/status")
def rbac_status():
    return get_rbac_status()
