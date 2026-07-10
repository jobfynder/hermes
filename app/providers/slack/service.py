from typing import Any


def slack_provider_status() -> dict[str, Any]:
    return {
        "provider": "slack",
        "configured": False,
        "status": "contract",
        "supports_webhook": True,
        "supports_files": True,
        "supports_outbound": True,
        "purpose": "normalized_slack_intake_contract",
    }


def normalize_slack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") or payload

    return {
        "channel": "slack",
        "source_message_id": str(
            event.get("client_msg_id")
            or event.get("event_ts")
            or event.get("ts")
            or payload.get("event_id")
            or "unknown"
        ),
        "sender": {
            "sender_id": event.get("user"),
            "sender_name": event.get("username"),
        },
        "workspace_id": payload.get("team_id") or event.get("team"),
        "conversation_id": event.get("channel"),
        "content_type": "mixed" if event.get("files") and event.get("text") else (
            "file" if event.get("files") else "text"
        ),
        "text": event.get("text") or "",
        "attachments": event.get("files") or [],
        "metadata": {
            "slack_event_type": event.get("type"),
            "thread_ts": event.get("thread_ts"),
            "provider": "slack",
        },
    }
