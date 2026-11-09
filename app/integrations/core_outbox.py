"""Durable outbox between Hermes and Jobfynder Core (Hermes proposes, Core executes).

Flow: parsed posts -> clusters (app/drafts/job_dedup.py) -> the canonical post
of each cluster that passes the readiness gate is ENQUEUED here -> a dispatcher
pushes queued rows to Core's POST /hermes/job/create, with retries, backoff, a
daily cap and a circuit breaker.

Enqueueing is always on (cheap, bounded, local). DISPATCH IS OFF by default:
it needs HERMES_CORE_PUSH_ENABLED=1 (plus the existing CORE_API_BASE_URL and
HERMES_SERVICE_TOKEN). Until Core's endpoint is confirmed to accept the
payload, the outbox simply accumulates a reviewable queue and nothing leaves
Hermes. Jobs land in Core as DRAFT regardless; nothing here publishes.

Only 'draft'-status posts (parser-confident, no review needed) are enqueued.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from app.drafts.pipeline import _FIELDS, _LATERAL
from app.runtime.db import cursor

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_READY = " AND ".join(f"({_FIELDS[k]})" for k in ("job_title", "employment_type", "location", "required_skills", "recruiter_email"))


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(os.getenv(name, str(default))), low), high)
    except ValueError:
        return default


def push_enabled() -> bool:
    return _flag("HERMES_CORE_PUSH_ENABLED", "0")


def enqueue_ready(limit: int = 500, days: int = 7) -> int:
    """Queue ONE ready post per cluster: the oldest member that is parser-
    confident ('draft') and passes the readiness gate (a cluster whose first
    post was incomplete can still be represented by a better duplicate)."""
    with cursor() as cur:
        cur.execute(
            f"""INSERT INTO core_job_outbox(draft_id, cluster_id)
                SELECT x.draft_id, x.cluster_id FROM (
                    SELECT DISTINCT ON (m.cluster_id) d.draft_id, m.cluster_id, d.created_at
                    FROM job_cluster_members m JOIN drafts d ON d.draft_id = m.draft_id {_LATERAL}
                    WHERE d.status = 'draft' AND d.draft_type='draft_job_requirement'
                      AND d.created_at > now() - make_interval(days => %s)
                      AND ({_READY})
                      AND NOT EXISTS (SELECT 1 FROM core_job_outbox o WHERE o.cluster_id = m.cluster_id)
                      AND NOT EXISTS (SELECT 1 FROM core_pushes p WHERE p.draft_id = d.draft_id AND p.status='pushed')
                    ORDER BY m.cluster_id, d.created_at) x
                ORDER BY x.created_at LIMIT %s
                ON CONFLICT DO NOTHING""",
            (days, limit),
        )
        return cur.rowcount


def _breaker_open(cur) -> bool:
    """Open when the last 5 dispatch attempts in the last 30 minutes all failed."""
    cur.execute(
        "SELECT state FROM core_job_outbox WHERE last_attempt_at > now() - interval '30 minutes' "
        "ORDER BY last_attempt_at DESC LIMIT 5"
    )
    states = [r["state"] for r in cur.fetchall()]
    return len(states) == 5 and all(s == "failed" for s in states)


def dispatch(batch: int = 20, push: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    if not push_enabled():
        return {"enabled": False}
    from app.drafts.service import get_draft_object
    from app.integrations.core_job_push import core_push_configured, push_job_to_core

    if not core_push_configured() and push is None:
        return {"enabled": True, "skipped": "core_push_not_configured"}
    push = push or push_job_to_core
    daily_cap = _int("HERMES_CORE_PUSH_DAILY_LIMIT", 200, 1, 5000)
    result = {"enabled": True, "pushed": 0, "failed": 0, "held": 0}

    with cursor() as cur:
        if _breaker_open(cur):
            return {**result, "skipped": "circuit_open"}
        cur.execute("SELECT count(*) AS n FROM core_job_outbox WHERE state='pushed' AND last_attempt_at > now() - interval '24 hours'")
        remaining = daily_cap - cur.fetchone()["n"]
        if remaining <= 0:
            return {**result, "skipped": "daily_limit"}
        cur.execute(
            "SELECT draft_id FROM core_job_outbox WHERE state IN ('ready','failed') AND attempts < %s "
            "AND next_attempt_at <= now() ORDER BY enqueued_at LIMIT %s FOR UPDATE SKIP LOCKED",
            (MAX_ATTEMPTS, min(batch, remaining)),
        )
        ids = [str(r["draft_id"]) for r in cur.fetchall()]

    for draft_id in ids:
        draft = get_draft_object(draft_id)
        if draft is None:  # expired/removed since it was queued
            _mark(draft_id, "held", error="draft_missing")
            result["held"] += 1
            continue
        outcome = push(draft)
        if outcome.get("status") == "pushed":
            _mark(draft_id, "pushed", core_job_id=outcome.get("core_job_id"))
            result["pushed"] += 1
        else:
            _mark(draft_id, "failed", error=str(outcome.get("reason", "unknown"))[:300], backoff=True)
            result["failed"] += 1
    return result


def _mark(draft_id: str, state: str, *, core_job_id: str | None = None, error: str | None = None, backoff: bool = False) -> None:
    with cursor() as cur:
        cur.execute(
            """UPDATE core_job_outbox SET state=%s, attempts=attempts+1, last_attempt_at=now(), updated_at=now(),
                   core_job_id=COALESCE(%s, core_job_id), last_error=%s,
                   next_attempt_at = CASE WHEN %s THEN now() + make_interval(mins => 10 * power(2, attempts)::int) ELSE next_attempt_at END
               WHERE draft_id=%s""",
            (state, core_job_id, error, backoff, draft_id),
        )


def get_outbox_stats() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SELECT state, count(*) AS n FROM core_job_outbox GROUP BY state")
        states = {r["state"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT left(last_error, 100) AS error, count(*) AS n FROM core_job_outbox WHERE state='failed' GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
        )
        errors = cur.fetchall()
    return {"dispatch_enabled": push_enabled(), "states": states, "top_errors": [dict(e) for e in errors]}


class PipelineScheduler:
    """Ticked by the backfill worker's idle branch (never during a backfill).
    Every `interval` seconds: cluster new posts, enqueue ready canonicals, and
    -- only when HERMES_CORE_PUSH_ENABLED -- dispatch. Errors are logged by
    class and never escape."""

    def __init__(self, interval: float = 60.0, first_delay: float = 120.0,
                 clock: Callable[[], float] = time.monotonic,
                 steps: Callable[[], dict[str, Any]] | None = None) -> None:
        self._interval = interval
        self._clock = clock
        self._steps = steps or self._default_steps
        self.next_run = clock() + first_delay

    @staticmethod
    def _default_steps() -> dict[str, Any]:
        from app.drafts.job_dedup import cluster_new_drafts

        out: dict[str, Any] = {}
        try:  # fill missing employment types first so they can be clustered/queued this tick
            from app.drafts.employment_priors import run_step

            out["employment_priors"] = run_step(_int("HERMES_EMPLOYMENT_PRIORS_BATCH", 300, 10, 2000))
        except Exception as exc:  # noqa: BLE001 - never block clustering/outbox
            logger.error("Employment priors step failed error=%s", type(exc).__name__)
        out["clustering"] = cluster_new_drafts(_int("HERMES_CLUSTER_BATCH", 500, 10, 5000))
        if _flag("HERMES_CORE_OUTBOX_ENABLED", "1"):
            out["enqueued"] = enqueue_ready()
            out["dispatch"] = dispatch()
        return out

    def tick(self) -> dict[str, Any] | None:
        now = self._clock()
        if now < self.next_run:
            return None
        self.next_run = now + self._interval
        try:
            return self._steps()
        except Exception as exc:  # noqa: BLE001
            logger.error("Pipeline step failed error=%s", type(exc).__name__)
            return None
