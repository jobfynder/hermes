from typing import Any

from app.email_parsing.routing import classify_recipient_mailbox
from app.email_parsing.sender_resolver import looks_forwarded, resolve_original_sender


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

    reply_to = payload.get("reply_to") or {}

    if isinstance(reply_to, str):
        reply_to = {"email": reply_to}

    reply_to_email = reply_to.get("email") or reply_to.get("address")

    subject = payload.get("subject") or ""
    body = (
        payload.get("text")
        or payload.get("body")
        or payload.get("plain_text")
        or ""
    )

    recipients = payload.get("to")
    intended_document_kind = classify_recipient_mailbox(recipients)

    # Some sources forward a posting rather than sending or CC'ing it
    # directly (e.g. a recruiter mailing list) -- the visible From is the
    # forwarder, not the recruiter who actually wrote it. Any downstream
    # claim-and-verify step that emails the "sender" back needs the real
    # recruiter, so recover it deterministically here, before the body is
    # cleaned/summarized downstream. See app/email_parsing/sender_resolver.py.
    original_sender_candidate = (
        resolve_original_sender(body, reply_to_email=reply_to_email)
        if looks_forwarded(body)
        else None
    )

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
            "original_sender_candidate": original_sender_candidate,
        },
    }
