from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

from app.runtime.jsonl_store import append_jsonl, runtime_path


EVENT_LOG = runtime_path("events", "events.jsonl")


def emit_event(
    event_type: str,
    payload: dict[str, Any],
    source: str = "hermes",
) -> dict[str, Any]:
    event = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "source": source,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }

    append_jsonl(EVENT_LOG, event)
    return event
