from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import (
    HERMES_PUBLIC_WEBHOOK_BASE_URL,
    HERMES_TELEGRAM_BOT_TOKEN,
    HERMES_TELEGRAM_WEBHOOK_SECRET,
)


def is_telegram_configured() -> bool:
    return bool(
        HERMES_PUBLIC_WEBHOOK_BASE_URL
        and HERMES_TELEGRAM_BOT_TOKEN
        and HERMES_TELEGRAM_WEBHOOK_SECRET
    )


def telegram_webhook_url() -> str:
    base = HERMES_PUBLIC_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/channels/telegram/webhook"


def telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{HERMES_TELEGRAM_BOT_TOKEN}/{method}"


def build_set_webhook_payload() -> dict[str, Any]:
    return {
        "url": telegram_webhook_url(),
        "secret_token": HERMES_TELEGRAM_WEBHOOK_SECRET,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    }


def register_telegram_webhook() -> dict[str, Any]:
    if not is_telegram_configured():
        return {
            "status": "blocked",
            "reason": "telegram_not_configured",
            "required_env": [
                "HERMES_PUBLIC_WEBHOOK_BASE_URL",
                "HERMES_TELEGRAM_BOT_TOKEN",
                "HERMES_TELEGRAM_WEBHOOK_SECRET",
            ],
        }

    payload = urlencode(build_set_webhook_payload(), doseq=True).encode("utf-8")
    request = Request(
        telegram_api_url("setWebhook"),
        data=payload,
        method="POST",
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")

    return {
        "status": "submitted",
        "provider": "telegram",
        "webhook_url": telegram_webhook_url(),
        "response": body,
    }


def telegram_provider_status() -> dict[str, Any]:
    return {
        "provider": "telegram",
        "configured": is_telegram_configured(),
        "webhook_url": telegram_webhook_url() if HERMES_PUBLIC_WEBHOOK_BASE_URL else None,
        "has_bot_token": bool(HERMES_TELEGRAM_BOT_TOKEN),
        "has_webhook_secret": bool(HERMES_TELEGRAM_WEBHOOK_SECRET),
    }

def send_telegram_message(
    chat_id: str | int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not HERMES_TELEGRAM_BOT_TOKEN:
        return {
            "status": "blocked",
            "reason": "telegram_bot_token_missing",
        }

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)

    encoded = urlencode(payload).encode("utf-8")
    request = Request(
        telegram_api_url("sendMessage"),
        data=encoded,
        method="POST",
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")

        return {
            "status": "submitted",
            "provider": "telegram",
            "response": body,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "provider": "telegram",
            "reason": "send_message_failed",
            "error": str(exc),
        }

def telegram_get_file(file_id: str) -> dict[str, Any]:
    if not HERMES_TELEGRAM_BOT_TOKEN:
        return {
            "status": "blocked",
            "reason": "telegram_bot_token_missing",
        }

    payload = urlencode({"file_id": file_id}).encode("utf-8")
    request = Request(
        telegram_api_url("getFile"),
        data=payload,
        method="POST",
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=15) as response:
            import json
            body = response.read().decode("utf-8")
            return json.loads(body)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def telegram_download_file(file_id: str) -> dict[str, Any]:
    file_info = telegram_get_file(file_id)

    if not file_info.get("ok"):
        return {
            "status": "failed",
            "reason": "telegram_get_file_failed",
            "provider_response": file_info,
        }

    file_path = file_info.get("result", {}).get("file_path")
    if not file_path:
        return {
            "status": "failed",
            "reason": "telegram_file_path_missing",
            "provider_response": file_info,
        }

    download_url = f"https://api.telegram.org/file/bot{HERMES_TELEGRAM_BOT_TOKEN}/{file_path}"

    try:
        with urlopen(download_url, timeout=30) as response:
            content = response.read()
            content_type = response.headers.get("content-type")
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "telegram_file_download_failed",
            "error": str(exc),
            "file_path": file_path,
        }

    return {
        "status": "downloaded",
        "file_id": file_id,
        "file_path": file_path,
        "filename": file_path.split("/")[-1],
        "content_type": content_type,
        "content": content,
    }

