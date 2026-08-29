"""Sender blocklist (HERMES-900): domains/addresses a human has decided to
stop hearing from. Checked at the very top of channel intake -- a match
means the message never becomes a draft at all (see sender_blocklist in
app/runtime/db.py for why: blocking should reduce review-queue clutter,
not just tag it after the fact).
"""

from __future__ import annotations

from app.runtime.db import cursor


def extract_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None

    return email.strip().lower().rsplit("@", 1)[-1] or None


def is_blocked(email: str | None) -> dict | None:
    """Returns the matching blocklist row (as a dict) if this address is
    blocked -- either directly, or via its domain -- else None. An exact
    email match is checked first: it is a strictly narrower rule, and
    should win over a same-domain block reason.
    """
    if not email:
        return None

    normalized_email = email.strip().lower()
    domain = extract_domain(normalized_email)

    with cursor() as cur:
        cur.execute(
            "SELECT id, match_type, value, reason FROM sender_blocklist "
            "WHERE (match_type = 'email' AND value = %s) "
            "OR (match_type = 'domain' AND value = %s) "
            "ORDER BY match_type ASC LIMIT 1",
            (normalized_email, domain),
        )
        row = cur.fetchone()

    return dict(row) if row else None


def add_block(
    match_type: str,
    value: str,
    reason: str | None = None,
    source_draft_id: str | None = None,
) -> dict:
    normalized_value = value.strip().lower()

    with cursor() as cur:
        cur.execute(
            "INSERT INTO sender_blocklist (match_type, value, reason, source_draft_id) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (match_type, value) DO UPDATE SET reason = COALESCE(EXCLUDED.reason, sender_blocklist.reason) "
            "RETURNING id, match_type, value, reason, source_draft_id, created_at",
            (match_type, normalized_value, reason, source_draft_id),
        )
        row = cur.fetchone()

    return dict(row)


def remove_block(block_id: int) -> bool:
    with cursor() as cur:
        cur.execute("DELETE FROM sender_blocklist WHERE id = %s", (block_id,))
        return cur.rowcount > 0


def list_blocks() -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT id, match_type, value, reason, source_draft_id, created_at "
            "FROM sender_blocklist ORDER BY created_at DESC"
        )
        return [dict(row) for row in cur.fetchall()]
