from app.security.rbac import require_admin_permission
from fastapi import APIRouter, Depends

from app.providers.telegram.service import (
    register_telegram_webhook,
    telegram_provider_status,
)

router = APIRouter(prefix="/providers/telegram", tags=["Telegram Provider"])


@router.get("/status")
def get_telegram_provider_status(_principal: dict = Depends(require_admin_permission("runtime:read"))) -> dict:
    return telegram_provider_status()


@router.post("/register-webhook")
def register_webhook(_principal: dict = Depends(require_admin_permission("drafts:publish"))) -> dict:
    return register_telegram_webhook()
