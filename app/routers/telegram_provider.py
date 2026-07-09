from fastapi import APIRouter

from app.providers.telegram.service import (
    register_telegram_webhook,
    telegram_provider_status,
)

router = APIRouter(prefix="/providers/telegram", tags=["Telegram Provider"])


@router.get("/status")
def get_telegram_provider_status() -> dict:
    return telegram_provider_status()


@router.post("/register-webhook")
def register_webhook() -> dict:
    return register_telegram_webhook()
