import json
from typing import Any

from app.runtime.db import cursor


def record_intake(record: dict[str, Any]) -> None:
    channel = record.get('channel', '')
    source_message_id = record.get('source_message_id')
    status = record.get('status', 'unknown')
    duplicate_key = record.get('duplicate_key', '')

    detail = {k: v for k, v in record.items() if k not in {'channel', 'source_message_id', 'status', 'duplicate_key'}}

    with cursor() as cur:
        cur.execute(
            'INSERT INTO intake_log (duplicate_key, channel, source_message_id, status, detail) '
            'VALUES (%s, %s, %s, %s, %s)',
            (duplicate_key, channel, source_message_id, status, json.dumps(detail, default=str)),
        )


def record_idempotency_key_if_new(key: str) -> bool:
    '''Atomically records a transport-dedupe key and reports whether it was
    actually new. Replaces the old load-once-into-an-in-memory-set
    approach, which was silently wrong across more than one process:
    hermes-api and hermes-graph-consumer each held their own independent
    snapshot taken at startup, so a duplicate one process had already seen
    was invisible to the other. A single INSERT ... ON CONFLICT against
    the shared database is both correct across processes and race-free
    within one (no separate check-then-insert window).
    '''
    with cursor() as cur:
        cur.execute(
            'INSERT INTO idempotency_keys (key) VALUES (%s) ON CONFLICT (key) DO NOTHING',
            (key,),
        )
        return cur.rowcount == 1
