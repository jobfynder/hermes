import json
from pathlib import Path
from typing import Any


RUNTIME_ROOT = Path("/hermes-runtime")


def runtime_path(*parts: str) -> Path:
    path = RUNTIME_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            cleaned = line.strip()
            if cleaned:
                records.append(json.loads(cleaned))

    return records


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))
