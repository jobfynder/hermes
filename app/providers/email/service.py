from typing import Any

from app.email_parsing.routing import classify_recipient_mailbox


def email_provider_status() -> dict[str, Any]:
    return {
        "provider": "email",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": False,
        "purpose": "normalized_email_intake_contract",
        "parser_mode": "deterministic",
        "uses_llm": False,
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
    body = (
        payload.get("text")
        or payload.get("body")
        or payload.get("plain_text")
        or ""
    )

    recipients = payload.get("to")
    intended_document_kind = classify_recipient_mailbox(recipients)

    return {
        "channel": "email",
        "source_message_id": str(message_id),
        "sender": {
            "sender_id": sender.get("email") or sender.get("address"),
            "sender_name": sender.get("name"),
            "email": sender.get("email") or sender.get("address"),
        },
        "content_type": (
            "mixed"
            if payload.get("attachments")
            else "text"
        ),
        "text": f"Subject: {subject}\n\n{body}".strip(),
        "attachments": payload.get("attachments", []),
        "received_at": payload.get("received_at"),
        "metadata": {
            "subject": subject,
            "to": recipients,
            "cc": payload.get("cc"),
            "provider": payload.get("provider"),
            "intended_document_kind": intended_document_kind,
            "parser_mode": "deterministic",
            "uses_llm": False,
        },
    }
