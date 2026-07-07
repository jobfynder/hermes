#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy.versioning import build_taxonomy_snapshot


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("HERMES-400 taxonomy snapshot check started")

    snapshot = build_taxonomy_snapshot(validation_status="passed")

    require(
        snapshot.get("result_version") == "hermes_taxonomy_snapshot_v1",
        "wrong taxonomy snapshot result_version",
    )
    require(
        snapshot.get("snapshot_name") == "hermes-400-taxonomy-foundation-v1",
        "wrong taxonomy snapshot name",
    )

    versions = snapshot.get("taxonomy_versions", {})
    counts = snapshot.get("counts", {})
    source_files = snapshot.get("source_files", {})

    for key in ["canonical_skills", "skill_aliases", "job_titles", "title_aliases"]:
        require(versions.get(key), f"missing taxonomy version for {key}")
        require(isinstance(counts.get(key), int), f"missing taxonomy count for {key}")
        require(counts.get(key) > 0, f"taxonomy count must be greater than 0 for {key}")
        require(source_files.get(key), f"missing source file for {key}")

    require(snapshot.get("validation_status") == "passed", "validation_status was not preserved")

    print("OK: taxonomy snapshot has version metadata")
    print("OK: taxonomy snapshot has counts")
    print("OK: taxonomy snapshot has source files")
    print("OK: taxonomy snapshot validation status is preserved")
    print("HERMES-400 taxonomy snapshot check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 taxonomy snapshot check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
