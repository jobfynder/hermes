from typing import Any


def email_provider_status() -> dict[str, Any]:
    return {
        "provider": "email",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": False,
        "purpose": "normalized_email_intake_contract",
    }


def normalize_email_payload(payload: dict[str, Any]) -> dict[str, Any]:
    message_id = (
        payload.get("message_id")
        or payload.get("email_id")
        or payload.get("id")
        or "unknown"
    )

    sender = payload.get("from") or payload.get("sender") or {}

    if isinstance(sender, str):
        sender = {"email": sender}

    subject = payload.get("subject") or ""
    body = payload.get("text") or payload.get("body") or payload.get("plain_text") or ""

    return {
        "channel": "email",
        "source_message_id": str(message_id),
        "sender": {
            "sender_id": sender.get("email") or sender.get("address"),
            "sender_name": sender.get("name"),
            "email": sender.get("email") or sender.get("address"),
        },
        "content_type": "text",
        "text": f"Subject: {subject}\n\n{body}".strip(),
        "attachments": payload.get("attachments", []),
        "metadata": {
            "subject": subject,
            "to": payload.get("to"),
            "cc": payload.get("cc"),
            "provider": payload.get("provider"),
        },
    }
