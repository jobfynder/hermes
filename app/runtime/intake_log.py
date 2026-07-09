from datetime import datetime, UTC
from typing import Any

from app.runtime.jsonl_store import append_jsonl, read_jsonl, runtime_path


INTAKE_LOG = runtime_path("intake", "intake.jsonl")
IDEMPOTENCY_LOG = runtime_path("intake", "idempotency.jsonl")


def record_intake(record: dict[str, Any]) -> None:
    append_jsonl(
        INTAKE_LOG,
        {
            "recorded_at": datetime.now(UTC).isoformat(),
            **record,
        },
    )


def record_idempotency_key(key: str) -> None:
    append_jsonl(
        IDEMPOTENCY_LOG,
        {
            "recorded_at": datetime.now(UTC).isoformat(),
            "key": key,
        },
    )


def load_idempotency_keys() -> set[str]:
    return {
        item["key"]
        for item in read_jsonl(IDEMPOTENCY_LOG)
        if item.get("key")
    }
