import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = "/hermes-runtime/prompt-runs"


def prompt_run_log_dir() -> Path:
    return Path(os.getenv("HERMES_PROMPT_RUN_LOG_DIR", DEFAULT_LOG_DIR))


def append_prompt_run(event: dict[str, Any]) -> str | None:
    log_dir = prompt_run_log_dir()

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"prompt-runs-{datetime.now(UTC).date().isoformat()}.jsonl"
        payload = {
            "recorded_at": datetime.now(UTC).isoformat(),
            **event,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        return str(path)
    except OSError:
        return None
