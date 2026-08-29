"""One-time import of the pre-database JSONL storage (drafts, field
provenance, claims, intake log) into the new Postgres landing database.

Run once, after the landing-database code is deployed and before/around
the same deploy, from inside the hermes-api container:

    docker exec hermes-api python scripts/hermes-landing-db-import-jsonl.py

Idempotent: every insert uses ON CONFLICT DO NOTHING keyed on the same
primary key the JSONL record already carries, so running this twice (or
running it after some new-format records have already landed via the
live app) never creates duplicates or overwrites newer data.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.runtime.db import cursor, init_schema

RUNTIME_ROOT = Path("/hermes-runtime")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def import_drafts() -> int:
    drafts_dir = RUNTIME_ROOT / "drafts"
    if not drafts_dir.exists():
        return 0

    count = 0
    with cursor() as cur:
        for path in drafts_dir.glob("*.json"):
            draft = _read_json(path)
            if not draft:
                continue

            cur.execute(
                """
                INSERT INTO drafts (
                    draft_id, draft_type, status, source, source_ref, channel,
                    source_message_id, title, summary, payload, normalized_skills,
                    normalized_job_titles, taxonomy_signals, confidence,
                    requires_review, errors, metadata
                ) VALUES (
                    %(draft_id)s, %(draft_type)s, %(status)s, %(source)s, %(source_ref)s,
                    %(channel)s, %(source_message_id)s, %(title)s, %(summary)s,
                    %(payload)s, %(normalized_skills)s, %(normalized_job_titles)s,
                    %(taxonomy_signals)s, %(confidence)s, %(requires_review)s,
                    %(errors)s, %(metadata)s
                )
                ON CONFLICT (draft_id) DO NOTHING
                """,
                {
                    "draft_id": draft["draft_id"],
                    "draft_type": draft["draft_type"],
                    "status": draft.get("status", "draft"),
                    "source": draft.get("source", "channel_text_intake"),
                    "source_ref": draft.get("source_ref"),
                    "channel": draft.get("channel"),
                    "source_message_id": draft.get("source_message_id"),
                    "title": draft.get("title"),
                    "summary": draft.get("summary"),
                    "payload": json.dumps(draft.get("payload", {}), default=str),
                    "normalized_skills": json.dumps(draft.get("normalized_skills", []), default=str),
                    "normalized_job_titles": json.dumps(draft.get("normalized_job_titles", []), default=str),
                    "taxonomy_signals": json.dumps(draft.get("taxonomy_signals", {}), default=str),
                    "confidence": draft.get("confidence", 0.0),
                    "requires_review": draft.get("requires_review", True),
                    "errors": json.dumps(draft.get("errors", []), default=str),
                    "metadata": json.dumps(draft.get("metadata", {}), default=str),
                },
            )
            count += 1
    return count


def import_provenance() -> int:
    provenance_dir = RUNTIME_ROOT / "provenance"
    if not provenance_dir.exists():
        return 0

    count = 0
    with cursor() as cur:
        for path in provenance_dir.glob("*.jsonl"):
            for entry in _read_jsonl(path):
                cur.execute(
                    """
                    INSERT INTO field_provenance (
                        parse_run_id, field_path, raw_value, normalized_value,
                        source_region, extractor, extraction_method, confidence, value_kind, recorded_at
                    ) VALUES (
                        %(parse_run_id)s, %(field_path)s, %(raw_value)s, %(normalized_value)s,
                        %(source_region)s, %(extractor)s, %(extraction_method)s, %(confidence)s,
                        %(value_kind)s, %(recorded_at)s
                    )
                    """,
                    {
                        "parse_run_id": entry.get("parse_run_id", path.stem),
                        "field_path": entry["field_path"],
                        "raw_value": (
                            entry.get("raw_value")
                            if isinstance(entry.get("raw_value"), str) or entry.get("raw_value") is None
                            else json.dumps(entry["raw_value"], default=str)
                        ),
                        "normalized_value": json.dumps(entry.get("normalized_value"), default=str),
                        "source_region": entry.get("source_region"),
                        "extractor": entry["extractor"],
                        "extraction_method": entry["extraction_method"],
                        "confidence": entry["confidence"],
                        "value_kind": entry["value_kind"],
                        "recorded_at": entry.get("recorded_at"),
                    },
                )
                count += 1
    return count


def import_claims() -> int:
    claims_dir = RUNTIME_ROOT / "claims" / "by_id"
    if not claims_dir.exists():
        return 0

    count = 0
    with cursor() as cur:
        for path in claims_dir.glob("*.json"):
            claim = _read_json(path)
            if not claim:
                continue

            cur.execute(
                """
                INSERT INTO email_claims (
                    claim_id, draft_id, token, status, recruiter_email, recruiter_name,
                    resolution_method, resolution_confidence, prefilled_fields, correction_diff,
                    created_at, sent_at, claimed_at, published_at, expires_at
                ) VALUES (
                    %(claim_id)s, %(draft_id)s, %(token)s, %(status)s, %(recruiter_email)s,
                    %(recruiter_name)s, %(resolution_method)s, %(resolution_confidence)s,
                    %(prefilled_fields)s, %(correction_diff)s, %(created_at)s, %(sent_at)s,
                    %(claimed_at)s, %(published_at)s, %(expires_at)s
                )
                ON CONFLICT (claim_id) DO NOTHING
                """,
                {
                    "claim_id": claim["claim_id"],
                    "draft_id": claim["draft_id"],
                    "token": claim["token"],
                    "status": claim.get("status", "PENDING_CLAIM"),
                    "recruiter_email": claim["recruiter_email"],
                    "recruiter_name": claim.get("recruiter_name"),
                    "resolution_method": claim["resolution_method"],
                    "resolution_confidence": claim.get("resolution_confidence", 0.0),
                    "prefilled_fields": json.dumps(claim.get("prefilled_fields", {}), default=str),
                    "correction_diff": (
                        json.dumps(claim["correction_diff"], default=str) if claim.get("correction_diff") else None
                    ),
                    "created_at": claim["created_at"],
                    "sent_at": claim.get("sent_at"),
                    "claimed_at": claim.get("claimed_at"),
                    "published_at": claim.get("published_at"),
                    "expires_at": claim["expires_at"],
                },
            )
            count += 1
    return count


def import_idempotency_keys() -> int:
    path = RUNTIME_ROOT / "intake" / "idempotency.jsonl"
    entries = _read_jsonl(path)

    count = 0
    with cursor() as cur:
        for entry in entries:
            key = entry.get("key")
            if not key:
                continue
            cur.execute(
                "INSERT INTO idempotency_keys (key, recorded_at) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (key, entry.get("recorded_at")),
            )
            count += 1
    return count


def import_content_hashes() -> int:
    path = RUNTIME_ROOT / "intake" / "content_hashes.jsonl"
    entries = _read_jsonl(path)

    count = 0
    with cursor() as cur:
        for entry in entries:
            body_hash = entry.get("body_hash")
            duplicate_key = entry.get("duplicate_key")
            if not body_hash or not duplicate_key:
                continue
            cur.execute(
                "INSERT INTO content_hash_index (body_hash, duplicate_key, recorded_at) "
                "VALUES (%s, %s, %s) ON CONFLICT (body_hash) DO NOTHING",
                (body_hash, duplicate_key, entry.get("recorded_at")),
            )
            count += 1
    return count


def main() -> None:
    init_schema()

    drafts = import_drafts()
    provenance = import_provenance()
    claims = import_claims()
    idempotency = import_idempotency_keys()
    content_hashes = import_content_hashes()

    print(
        f"Imported: {drafts} drafts, {provenance} provenance rows, {claims} claims, "
        f"{idempotency} idempotency keys, {content_hashes} content-hash entries."
    )


if __name__ == "__main__":
    main()
