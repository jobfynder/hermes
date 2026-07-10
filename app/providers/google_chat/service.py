from typing import Any


def google_chat_provider_status() -> dict[str, Any]:
    return {
        "provider": "google_chat",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": True,
        "purpose": "normalized_google_chat_intake_contract",
    }


def normalize_google_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") or payload
    sender = message.get("sender") or {}
    space = message.get("space") or {}

    return {
        "channel": "google_chat",
        "source_message_id": str(
            message.get("name")
            or message.get("message_id")
            or "unknown"
        ),
        "sender": {
            "sender_id": sender.get("name"),
            "sender_name": sender.get("displayName"),
            "email": sender.get("email"),
        },
        "conversation_id": space.get("name"),
        "content_type": "mixed" if message.get("attachment") and message.get("text") else (
            "file" if message.get("attachment") else "text"
        ),
        "text": message.get("text") or message.get("argumentText") or "",
        "attachments": message.get("attachment") or [],
        "received_at": message.get("createTime"),
        "metadata": {
            "space_type": space.get("type"),
            "thread": message.get("thread"),
            "provider": "google_chat",
        },
    }
