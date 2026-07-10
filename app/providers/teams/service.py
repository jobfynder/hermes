from typing import Any


def teams_provider_status() -> dict[str, Any]:
    return {
        "provider": "teams",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": True,
        "purpose": "normalized_teams_intake_contract",
    }


def normalize_teams_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sender = payload.get("from") or {}
    conversation = payload.get("conversation") or {}

    return {
        "channel": "teams",
        "source_message_id": str(payload.get("id") or "unknown"),
        "sender": {
            "sender_id": sender.get("id"),
            "sender_name": sender.get("name"),
        },
        "conversation_id": conversation.get("id"),
        "content_type": "mixed" if payload.get("attachments") and payload.get("text") else (
            "file" if payload.get("attachments") else "text"
        ),
        "text": payload.get("text") or "",
        "attachments": payload.get("attachments") or [],
        "received_at": payload.get("timestamp"),
        "metadata": {
            "service_url": payload.get("serviceUrl"),
            "channel_id": payload.get("channelId"),
            "provider": "teams",
        },
    }
