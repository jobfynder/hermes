"""In-Hermes automation of the taxonomy and sender-blocklist review queues.

Why: pending taxonomy candidates had grown to ~36k skills, ~18k job titles
and ~517k boilerplate lines. Nearly all were one-off noise (recruiter and
company names, single-vendor template sentences, one-sighting terms). The
host timer hermes-taxonomy-triage.timer already reviews NEW evidence every 15
minutes, but it never retires terms that stay ambiguous, so the backlog just
sat there. This module, run daily from the existing backfill worker (no model
calls), adds the bulk evidence rules that runner lacks and automates the
blocklist for the clear-cut cases. Running the triage stages from here as
well is optional (HERMES_REVIEW_AUTOMATION_RUN_TRIAGE=1) and shares the
runner's advisory lock.

Safety:
* Rejections here are retire-not-delete. A row rejected by an automatic
  reviewer (hermes-*) is revived to pending if later evidence reaches the
  approval bar (several senders, several sightings). Human decisions
  (any other reviewed_by) are never touched or revived.
* Approvals only come from the existing triage thresholds (technical shape,
  occurrences and distinct sender domains); this module adds none.
* Auto-blocks are capped per run, only for non-shared domains / repeatedly
  rejected single addresses, carry an "auto:" reason, and are removable from
  the existing blocklist screen. Kill switch: HERMES_REVIEW_AUTOMATION_ENABLED=0.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from app.runtime.db import cursor
from app.runtime.events import emit_event

logger = logging.getLogger(__name__)

_TRIAGE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "hermes-900-daily-taxonomy-triage.py"
_AUTO_REVIEWERS = ("hermes-auto-template", "hermes-stale-observation")

TEMPLATE_MIN_OCCURRENCES = 8
STALE_DAYS = 30


def automation_enabled() -> bool:
    return os.getenv("HERMES_REVIEW_AUTOMATION_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _beat() -> None:
    """Keep the worker health-check heartbeat fresh during a long pass."""
    try:
        Path(os.getenv("HERMES_WORKER_HEARTBEAT", "/tmp/hermes-backfill-heartbeat")).touch()
    except OSError:
        pass


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(os.getenv(name, str(default))), low), high)
    except ValueError:
        return default


_triage_module = None


def _triage():
    global _triage_module
    if _triage_module is None:
        spec = importlib.util.spec_from_file_location("hermes_daily_taxonomy_triage", _TRIAGE_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        _triage_module = module
    return _triage_module


def reject_single_sender_templates() -> int:
    """A 'skill' seen 8+ times but from a single sender domain is that
    vendor's own template text ("Interview Time Availability", a recruiter's
    name in a signature), not independent evidence of a skill."""
    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status='rejected', reviewed_at=now(), reviewed_by='hermes-auto-template' "
            "WHERE status='pending' AND signal_type='skill' AND occurrence_count >= %s "
            "AND jsonb_array_length(distinct_senders) <= 1",
            (TEMPLATE_MIN_OCCURRENCES,),
        )
        return cur.rowcount


def retire_stale_observations(limit: int = 20000) -> int:
    """One- and two-sighting terms from a single sender that have not
    reappeared for STALE_DAYS (the boilerplate queue already does this)."""
    with cursor() as cur:
        cur.execute(
            "WITH stale AS (SELECT id FROM taxonomy_candidates WHERE status='pending' "
            "AND signal_type IN ('skill','job_title') AND occurrence_count < 3 "
            "AND jsonb_array_length(distinct_senders) < 2 "
            "AND last_seen_at < now() - make_interval(days => %s) ORDER BY last_seen_at LIMIT %s) "
            "UPDATE taxonomy_candidates t SET status='rejected', reviewed_at=now(), reviewed_by='hermes-stale-observation' "
            "FROM stale WHERE t.id = stale.id",
            (STALE_DAYS, limit),
        )
        return cur.rowcount


def revive_recovered_candidates() -> int:
    """Self-correction: an automatically rejected term that later shows up
    across several senders goes back to pending for the normal rules."""
    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status='pending', reviewed_at=NULL, reviewed_by='hermes-revived' "
            "WHERE status='rejected' AND signal_type IN ('skill','job_title') AND reviewed_by = ANY(%s) "
            "AND occurrence_count >= 5 AND jsonb_array_length(distinct_senders) >= 3",
            (list(_AUTO_REVIEWERS),),
        )
        return cur.rowcount


def _run_triage_under_lock() -> dict[str, Any]:
    """Optional: also run the deterministic triage stages from inside Hermes.
    Off by default because the host timer hermes-taxonomy-triage.timer already
    runs them every 15 minutes; when enabled it takes the same advisory lock
    as that runner, so the two can never overlap."""
    triage = _triage()
    with triage.singleton() as acquired:
        if not acquired:
            return {"skipped": "another triage run is active"}
        results, failed = triage.run_stages(max_seconds=300)
        return {"failed": failed, **results}


def run_taxonomy_automation() -> dict[str, Any]:
    """The bulk rules the 15-minute triage runner does not have (it only
    reviews new evidence, so one-off noise never leaves the queue)."""
    summary: dict[str, Any] = {
        "templates_rejected": reject_single_sender_templates(),
        "stale_retired": retire_stale_observations(),
        "revived": revive_recovered_candidates(),
    }
    _beat()
    if os.getenv("HERMES_REVIEW_AUTOMATION_RUN_TRIAGE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        summary["triage"] = _run_triage_under_lock()
    return summary


def run_review_automation() -> dict[str, Any]:
    """One full daily pass (taxonomy + blocklist), recorded in
    review_automation_runs. Never raises."""
    from app.email_parsing.auto_blocklist import run_auto_blocklist

    started = time.monotonic()
    summary: dict[str, Any] = {}
    try:
        summary["taxonomy"] = run_taxonomy_automation()
    except Exception as exc:  # noqa: BLE001
        summary["taxonomy_error"] = type(exc).__name__
        logger.error("Taxonomy automation failed error=%s", type(exc).__name__)
    try:
        summary["blocklist"] = run_auto_blocklist()
    except Exception as exc:  # noqa: BLE001
        summary["blocklist_error"] = type(exc).__name__
        logger.error("Auto blocklist failed error=%s", type(exc).__name__)
    summary["seconds"] = round(time.monotonic() - started, 1)
    with cursor() as cur:
        cur.execute("INSERT INTO review_automation_runs (summary) VALUES (%s)", (json.dumps(summary),))
        cur.execute("DELETE FROM review_automation_runs WHERE ran_at < now() - interval '90 days'")
    emit_event("review.automation_ran", summary)
    logger.info("Review automation pass complete %s", json.dumps(summary))
    return summary


def last_run() -> dict[str, Any] | None:
    with cursor() as cur:
        cur.execute("SELECT ran_at, summary FROM review_automation_runs ORDER BY ran_at DESC LIMIT 1")
        row = cur.fetchone()
    return {"ran_at": row["ran_at"].isoformat(), "summary": row["summary"]} if row else None


def get_automation_status() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute(
            "SELECT signal_type, count(*) AS n FROM taxonomy_candidates WHERE status='pending' GROUP BY 1 ORDER BY 1"
        )
        pending = {row["signal_type"]: row["n"] for row in cur.fetchall()}
        cur.execute("SELECT count(*) AS n FROM sender_blocklist WHERE reason LIKE 'auto:%%'")
        auto_blocks = cur.fetchone()["n"]
    return {
        "enabled": automation_enabled(),
        "interval_hours": _env_int("HERMES_REVIEW_AUTOMATION_INTERVAL_HOURS", 24, 1, 168),
        "pending_candidates": pending,
        "auto_blocks_active": auto_blocks,
        "last_run": last_run(),
    }


class ReviewAutomationScheduler:
    """Ticked from the backfill worker's idle branch. Checks the database at
    most every `check_seconds`; the last-run row (not process memory) decides
    whether a pass is due, so restarts neither skip nor repeat a day."""

    def __init__(
        self,
        check_seconds: float = 600.0,
        first_delay_seconds: float = 180.0,
        clock: Callable[[], float] = time.monotonic,
        runner: Callable[[], dict[str, Any]] = run_review_automation,
        due: Callable[[], bool] | None = None,
    ) -> None:
        self._check = check_seconds
        self._clock = clock
        self._runner = runner
        self._due = due or self._default_due
        self.next_check = clock() + first_delay_seconds

    @staticmethod
    def _default_due() -> bool:
        hours = _env_int("HERMES_REVIEW_AUTOMATION_INTERVAL_HOURS", 24, 1, 168)
        with cursor() as cur:
            cur.execute("SELECT (max(ran_at) IS NULL OR max(ran_at) < now() - make_interval(hours => %s)) AS due FROM review_automation_runs", (hours,))
            return bool(cur.fetchone()["due"])

    def tick(self) -> bool:
        if not automation_enabled():
            return False
        now = self._clock()
        if now < self.next_check:
            return False
        self.next_check = now + self._check
        try:
            if not self._due():
                return False
            self._runner()
            return True
        except Exception as exc:  # noqa: BLE001 - never break the worker loop
            logger.error("Review automation tick failed error=%s", type(exc).__name__)
            return False
