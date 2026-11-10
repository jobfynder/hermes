from typing import Any

from fastapi import APIRouter, Depends

from app.security.rbac import require_permission

router = APIRouter(prefix="/sync", tags=["Sync status"])


@router.get("/status")
def sync_status(refresh: bool = False, _user: dict = Depends(require_permission("drafts:read"))) -> dict[str, Any]:
    """Parsing flow + Hermes -> Twenty CRM sync health. Read-only; cached ~45s."""
    from app.integrations.twenty_sync_monitor import get_status

    return get_status(force=refresh)
