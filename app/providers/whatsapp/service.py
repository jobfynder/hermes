from typing import Any


def whatsapp_provider_status() -> dict[str, Any]:
    return {
        "provider": "whatsapp",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": True,
        "purpose": "normalized_whatsapp_intake_contract",
    }


def normalize_whatsapp_payload(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") or payload

    sender_id = (
        message.get("from")
        or message.get("sender_id")
        or payload.get("from")
        or "unknown"
    )

    message_id = (
        message.get("id")
        or message.get("message_id")
        or payload.get("message_id")
        or "unknown"
    )

    text_value = message.get("text") or payload.get("text") or ""

    if isinstance(text_value, dict):
        text_value = text_value.get("body") or ""

    attachments = payload.get("attachments", [])

    return {
        "channel": "whatsapp",
        "source_message_id": str(message_id),
        "sender": {
            "sender_id": str(sender_id),
            "phone": str(sender_id),
        },
        "conversation_id": str(
            payload.get("conversation_id")
            or message.get("conversation_id")
            or sender_id
        ),
        "content_type": "mixed" if attachments and text_value else (
            "file" if attachments else "text"
        ),
        "text": text_value,
        "attachments": attachments,
        "metadata": {
            "provider": payload.get("provider") or "contract",
            "provider_payload_type": payload.get("type"),
        },
    }
