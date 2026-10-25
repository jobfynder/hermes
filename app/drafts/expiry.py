"""Automatic expiry of stale needs_review drafts.

A draft that is still waiting for review HERMES_REVIEW_EXPIRY_DAYS (default
7) days after it arrived is removed from the working `drafts` table, so the
review queue stays a list of recent postings instead of an ever-growing pile
of expired requirements. Runs inside Hermes itself -- the single supervised
backfill worker (scripts/hermes-backfill-worker.py) ticks the scheduler
below -- so it depends on no external cron/automation.

Safety, because this deletes production rows:

* Snapshot first. Every draft is copied in full (to_jsonb) into
  `expired_review_drafts` in the SAME transaction that deletes it, and kept
  HERMES_REVIEW_EXPIRY_ARCHIVE_DAYS (default 30) days. restore_expired_draft
  puts one back into needs_review with a fresh clock.
* Only needs_review. draft / rejected / spam / published are never touched.
* Never a draft a human has worked on (reviewer/recruiter correction) and
  never one referenced by an email claim or a Core push.
* Bounded. At most HERMES_REVIEW_EXPIRY_BATCH rows per transaction (FOR
  UPDATE SKIP LOCKED, so it never blocks or fights a reviewer editing the
  same row), with lock/statement timeouts.
* Age is measured from created_at (when the email arrived), not updated_at,
  so reparse/backfill jobs that touch a draft cannot keep it alive forever.
* Kill switch: HERMES_REVIEW_EXPIRY_DAYS=0 disables it entirely.

Deleting a draft also removes its field_provenance rows, and company_
observations / company_projection_state rows cascade by their foreign keys
(company discovery for that draft is dropped with it).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Callable

from app import config
from app.email_parsing.provenance import CORRECTION_EXTRACTORS
from app.runtime.db import cursor
from app.runtime.events import emit_event

logger = logging.getLogger(__name__)

_ELIGIBLE = """
    d.status = 'needs_review'
    AND d.created_at < now() - make_interval(days => %(ttl)s)
    AND NOT EXISTS (SELECT 1 FROM email_claims c WHERE c.draft_id = d.draft_id)
    AND NOT EXISTS (SELECT 1 FROM core_pushes p WHERE p.draft_id = d.draft_id)
    AND NOT EXISTS (
        SELECT 1 FROM field_provenance fp
        WHERE fp.parse_run_id = d.draft_id::text AND fp.extractor = ANY(%(extractors)s)
    )
"""


def expire_batch(ttl_days: int, batch_size: int) -> int:
    """Archive then delete up to batch_size eligible drafts in ONE
    transaction. Returns how many were removed."""
    params = {"ttl": ttl_days, "extractors": list(CORRECTION_EXTRACTORS), "n": batch_size}
    with cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute("SET LOCAL statement_timeout = '60s'")
        cur.execute(
            f"""SELECT d.draft_id FROM drafts d WHERE {_ELIGIBLE}
                ORDER BY d.created_at LIMIT %(n)s FOR UPDATE OF d SKIP LOCKED""",
            params,
        )
        ids = [row["draft_id"] for row in cur.fetchall()]
        if not ids:
            return 0

        cur.execute(
            """INSERT INTO expired_review_drafts
                   (draft_id, draft_type, source_message_id, draft_created_at, ttl_days, snapshot)
               SELECT d.draft_id, d.draft_type, d.source_message_id, d.created_at, %s, to_jsonb(d)
               FROM drafts d WHERE d.draft_id = ANY(%s)
               ON CONFLICT (draft_id) DO NOTHING""",
            (ttl_days, ids),
        )
        cur.execute("DELETE FROM field_provenance WHERE parse_run_id = ANY(%s)", ([str(i) for i in ids],))
        cur.execute("DELETE FROM drafts WHERE draft_id = ANY(%s)", (ids,))
        return cur.rowcount


def purge_archive(archive_days: int) -> int:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM expired_review_drafts WHERE expired_at < now() - make_interval(days => %s)",
            (archive_days,),
        )
        purged = cur.rowcount
        cur.execute("DELETE FROM review_expiry_runs WHERE ran_at < now() - interval '90 days'")
    return purged


def run_expiry_cycle(
    ttl_days: int | None = None,
    batch_size: int | None = None,
    archive_days: int | None = None,
) -> dict[str, Any]:
    """One bounded pass. `more` is True when the batch came back full, i.e.
    there is probably more due and the caller should come back soon."""
    ttl = config.HERMES_REVIEW_EXPIRY_DAYS if ttl_days is None else ttl_days
    if ttl <= 0:
        return {"enabled": False, "expired": 0, "purged": 0, "more": False}

    batch = config.HERMES_REVIEW_EXPIRY_BATCH if batch_size is None else batch_size
    keep = config.HERMES_REVIEW_EXPIRY_ARCHIVE_DAYS if archive_days is None else archive_days

    expired = expire_batch(ttl, batch)
    purged = purge_archive(keep) if expired < batch else 0

    if expired or purged:
        with cursor() as cur:
            cur.execute(
                "INSERT INTO review_expiry_runs (ttl_days, expired_count, purged_archive) VALUES (%s, %s, %s)",
                (ttl, expired, purged),
            )
        emit_event("drafts.review_expired", {"expired": expired, "ttl_days": ttl, "purged_archive": purged})
        logger.info("Review expiry removed %s needs_review drafts older than %s days (purged %s archived)", expired, ttl, purged)

    return {"enabled": True, "expired": expired, "purged": purged, "more": expired >= batch}


class ReviewExpiryScheduler:
    """Time-gated wrapper the worker loop ticks on every iteration. Cheap
    when nothing is due (one clock read). After a full batch it asks to be
    called again almost immediately so a large backlog drains in seconds
    rather than one batch per interval; otherwise it waits out the
    interval. Errors are logged by class only (messages can carry email
    content) and never escape into the worker loop."""

    def __init__(
        self,
        interval_seconds: int | None = None,
        first_delay_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        runner: Callable[[], dict[str, Any]] = run_expiry_cycle,
    ) -> None:
        self.interval = config.HERMES_REVIEW_EXPIRY_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        self._clock = clock
        self._runner = runner
        self.next_due = clock() + first_delay_seconds

    def tick(self) -> int:
        now = self._clock()
        if now < self.next_due:
            return 0
        try:
            result = self._runner()
        except Exception as exc:  # noqa: BLE001 - never break the worker loop
            logger.error("Review expiry cycle failed error=%s", type(exc).__name__)
            self.next_due = now + self.interval
            return 0
        self.next_due = now + (1.0 if result.get("more") else self.interval)
        return int(result.get("expired", 0))


def restore_expired_draft(draft_id: str) -> dict[str, Any]:
    """Undo one expiry: re-insert the archived snapshot as needs_review with
    a fresh created_at (a new full TTL window -- otherwise the next cycle
    would expire it again immediately). field_provenance is not restored;
    a review reparse regenerates it."""
    with cursor() as cur:
        cur.execute("SELECT snapshot FROM expired_review_drafts WHERE draft_id = %s FOR UPDATE", (draft_id,))
        row = cur.fetchone()
        if not row:
            return {"restored": False, "reason": "not_in_archive"}
        cur.execute("SELECT 1 FROM drafts WHERE draft_id = %s", (draft_id,))
        if cur.fetchone():
            return {"restored": False, "reason": "draft_already_exists"}

        now_iso = datetime.now(UTC).isoformat()
        snapshot = dict(row["snapshot"])
        snapshot["status"] = "needs_review"
        snapshot["created_at"] = now_iso
        snapshot["updated_at"] = now_iso
        snapshot["metadata"] = {**(snapshot.get("metadata") or {}), "restored_from_expiry": now_iso}
        cur.execute(
            "INSERT INTO drafts SELECT * FROM jsonb_populate_record(NULL::drafts, %s::jsonb)",
            (json.dumps(snapshot, default=str),),
        )
        cur.execute("DELETE FROM expired_review_drafts WHERE draft_id = %s", (draft_id,))
    emit_event("drafts.review_expiry_restored", {"draft_id": str(draft_id)})
    return {"restored": True}


def get_expiry_status() -> dict[str, Any]:
    ttl = config.HERMES_REVIEW_EXPIRY_DAYS
    with cursor() as cur:
        due_now = 0
        if ttl > 0:
            cur.execute(
                f"SELECT count(*) AS n FROM drafts d WHERE {_ELIGIBLE}",
                {"ttl": ttl, "extractors": list(CORRECTION_EXTRACTORS)},
            )
            due_now = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n, min(created_at) AS oldest FROM drafts WHERE status = 'needs_review'")
        queue = cur.fetchone()
        cur.execute("SELECT count(*) AS n FROM expired_review_drafts")
        archived = cur.fetchone()["n"]
        cur.execute("SELECT coalesce(sum(expired_count), 0)::int AS n FROM review_expiry_runs WHERE ran_at > now() - interval '24 hours'")
        last_24h = cur.fetchone()["n"]
        cur.execute("SELECT ran_at, ttl_days, expired_count, purged_archive FROM review_expiry_runs ORDER BY ran_at DESC LIMIT 1")
        last = cur.fetchone()

    return {
        "enabled": ttl > 0,
        "ttl_days": ttl,
        "interval_seconds": config.HERMES_REVIEW_EXPIRY_INTERVAL_SECONDS,
        "batch_size": config.HERMES_REVIEW_EXPIRY_BATCH,
        "archive_days": config.HERMES_REVIEW_EXPIRY_ARCHIVE_DAYS,
        "needs_review_total": queue["n"],
        "oldest_needs_review_at": queue["oldest"].isoformat() if queue["oldest"] else None,
        "due_now": due_now,
        "archived_restorable": archived,
        "expired_last_24h": last_24h,
        "last_run": (
            {
                "ran_at": last["ran_at"].isoformat(),
                "ttl_days": last["ttl_days"],
                "expired_count": last["expired_count"],
                "purged_archive": last["purged_archive"],
            }
            if last
            else None
        ),
    }
