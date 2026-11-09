"""One call that answers the three questions a person asks every morning:

  1. Is everything running?            -> `health`
  2. What needs ME today?              -> `inbox`  (only human work, with counts)
  3. What did Hermes do by itself?     -> `automation`, plus `pipeline` progress

Read-only and best effort: each section is computed independently, so a slow
or failing section degrades to {"error": ...} instead of blanking the page.
The whole payload is cached briefly because several people (and the page's own
refresh) can ask at once and the underlying counts scan large tables.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.runtime.db import cursor

logger = logging.getLogger(__name__)

_CACHE_SECONDS = 45.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one section must never blank the page
        logger.warning("workbench section failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


def _age_minutes(ts: datetime | str | None) -> float | None:
    if not ts:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - ts).total_seconds() / 60.0, 1)


def _status_file() -> dict[str, Any]:
    path = Path(os.getenv("HERMES_TAXONOMY_TRIAGE_STATUS_FILE", "/hermes-runtime/automation/taxonomy/status.json"))
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _intake() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '8s'")
        cur.execute(
            "SELECT max(created_at) AS last_at, "
            "count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS last_24h "
            "FROM drafts WHERE created_at > now() - interval '3 days'"
        )
        row = cur.fetchone()
    return {"last_email_at": row["last_at"].isoformat() if row["last_at"] else None,
            "last_email_minutes_ago": _age_minutes(row["last_at"]), "emails_last_24h": row["last_24h"]}


def _jobs() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute(
            "SELECT job_id, kind, status, processed_count, total_count, failed_count, updated_at "
            "FROM draft_backfill_jobs WHERE status IN ('running','queued','paused') "
            "ORDER BY created_at DESC LIMIT 1"
        )
        active = cur.fetchone()
    if not active:
        return {"active": None}
    total = active["total_count"] or 0
    return {"active": {
        "job_id": str(active["job_id"]), "kind": active["kind"], "status": active["status"],
        "processed": active["processed_count"], "total": total, "failed": active["failed_count"],
        "percent": round(100.0 * active["processed_count"] / total, 1) if total else 0.0,
        "updated_minutes_ago": _age_minutes(active["updated_at"]),
    }}


def _taxonomy_queue() -> dict[str, Any]:
    from app.reporting.service import get_candidate_queue_health

    return get_candidate_queue_health()


def _drafts_queue() -> dict[str, Any]:
    from app.drafts.expiry import get_expiry_status

    s = get_expiry_status()
    return {"needs_review": s["needs_review_total"], "oldest_needs_review_at": s["oldest_needs_review_at"],
            "expires_after_days": s["ttl_days"], "due_to_expire_now": s["due_now"],
            "removed_last_24h": s["expired_last_24h"], "restorable": s["archived_restorable"],
            "expiry_enabled": s["enabled"]}


def _pipeline() -> dict[str, Any]:
    from app.drafts.pipeline import get_pipeline_stats

    s = get_pipeline_stats(14)
    return {
        "window_days": s["window_days"], "live_posts": s["considered"], "ready": s["ready_for_core"],
        "ready_pct": s["ready_pct"], "only_employment_type_missing": s["only_employment_type_missing"],
        "fill_rates_pct": s["fill_rates_pct"], "missing_by_blocker": s["missing_by_blocker"],
        "distinct_roles": s["clusters"].get("clusters", 0),
        "roles_with_duplicates": s["clusters"].get("clusters_with_duplicates", 0),
        "outbox": s["outbox"], "core_pushes": s["core_pushes"],
    }


def _automation() -> dict[str, Any]:
    from app.drafts.expiry import get_expiry_status
    from app.understanding.taxonomy.automation import get_automation_status

    triage = _status_file()
    results = triage.get("results", {})
    auto = get_automation_status()
    expiry = get_expiry_status()
    return {
        "triage": {
            "last_run_at": triage.get("finished_at"), "minutes_ago": _age_minutes(triage.get("finished_at")),
            "status": triage.get("status"), "policy": triage.get("policy"),
            "skills": results.get("skills"), "titles": results.get("titles"),
            "boilerplate": results.get("boilerplate"),
        },
        "daily_cleanup": {"enabled": auto["enabled"], "last_run": auto.get("last_run"),
                          "auto_blocks_active": auto["auto_blocks_active"]},
        "expiry": {"enabled": expiry["enabled"], "removed_last_24h": expiry["expired_last_24h"],
                   "ttl_days": expiry["ttl_days"]},
    }


def _health(sections: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(key: str, label: str, status: str, detail: str) -> None:
        checks.append({"id": key, "label": label, "status": status, "detail": detail})

    intake = sections.get("intake") or {}
    if "error" in intake:
        add("intake", "Email intake", "warn", "Could not check recent emails.")
    else:
        mins = intake.get("last_email_minutes_ago")
        if mins is None:
            add("intake", "Email intake", "fail", "No emails received in the last 3 days.")
        elif mins > 360:
            add("intake", "Email intake", "fail", f"Last email arrived {round(mins / 60)} hours ago.")
        elif mins > 90:
            add("intake", "Email intake", "warn", f"Last email arrived {round(mins)} minutes ago.")
        else:
            add("intake", "Email intake", "ok", f"{intake['emails_last_24h']:,} emails in the last 24 hours.")

    auto = sections.get("automation") or {}
    triage = auto.get("triage") or {}
    if "error" in auto or triage.get("minutes_ago") is None:
        add("triage", "Automatic review (every 15 min)", "warn", "No run recorded yet.")
    elif triage.get("status") != "success":
        add("triage", "Automatic review (every 15 min)", "fail", "The last automatic review run failed.")
    elif triage["minutes_ago"] > 60:
        add("triage", "Automatic review (every 15 min)", "warn", f"Last ran {round(triage['minutes_ago'])} minutes ago.")
    else:
        add("triage", "Automatic review (every 15 min)", "ok", f"Last ran {round(triage['minutes_ago'])} minutes ago.")

    cleanup = (auto.get("daily_cleanup") or {})
    last = (cleanup.get("last_run") or {}).get("ran_at")
    mins = _age_minutes(last)
    if not cleanup.get("enabled", True):
        add("cleanup", "Daily clean-up", "warn", "Switched off.")
    elif mins is None:
        add("cleanup", "Daily clean-up", "warn", "Has not run yet.")
    elif mins > 36 * 60:
        add("cleanup", "Daily clean-up", "warn", f"Last ran {round(mins / 60)} hours ago.")
    else:
        add("cleanup", "Daily clean-up", "ok", f"Last ran {round(mins / 60)} hours ago.")

    jobs = sections.get("jobs") or {}
    active = jobs.get("active") if isinstance(jobs, dict) else None
    if active:
        stalled = (active.get("updated_minutes_ago") or 0) > 20 and active["status"] == "running"
        add("reparse", "Re-processing old emails", "warn" if stalled else "ok",
            f"{active['percent']}% done ({active['processed']:,} of {active['total']:,})."
            + (" No progress for 20+ minutes." if stalled else ""))

    pipeline = sections.get("pipeline") or {}
    outbox = pipeline.get("outbox") or {}
    if outbox:
        failed = (outbox.get("states") or {}).get("failed", 0)
        if not outbox.get("dispatch_enabled"):
            add("core", "Sending jobs to Jobfynder Core", "ok", "Switched off on purpose (nothing is sent yet).")
        elif failed:
            add("core", "Sending jobs to Jobfynder Core", "fail", f"{failed} jobs failed to send.")
        else:
            add("core", "Sending jobs to Jobfynder Core", "ok", "Sending normally.")
    return checks


def build_today() -> dict[str, Any]:
    builders: dict[str, Callable[[], Any]] = {
        "intake": _intake, "jobs": _jobs, "taxonomy_queue": _taxonomy_queue,
        "drafts_queue": _drafts_queue, "pipeline": _pipeline, "automation": _automation,
    }
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="hermes-today") as pool:
        futures = {key: pool.submit(_safe, fn) for key, fn in builders.items()}
        sections = {key: future.result() for key, future in futures.items()}

    queue = sections["taxonomy_queue"] if "error" not in sections["taxonomy_queue"] else {}
    drafts_q = sections["drafts_queue"] if "error" not in sections["drafts_queue"] else {}
    inbox = {
        "drafts": drafts_q,
        "skills": (queue.get("skill") or {}).get("pending_count"),
        "job_titles": (queue.get("job_title") or {}).get("pending_count"),
        "boilerplate": (queue.get("boilerplate_line") or {}).get("pending_count"),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "health": _health(sections),
        "inbox": inbox,
        "pipeline": sections["pipeline"],
        "automation": sections["automation"],
        "jobs": sections["jobs"],
        "intake": sections["intake"],
    }


def get_today(force: bool = False) -> dict[str, Any]:
    with _lock:
        if not force and _cache["value"] is not None and time.monotonic() - _cache["at"] < _CACHE_SECONDS:
            return _cache["value"]
    value = build_today()
    with _lock:
        _cache["value"], _cache["at"] = value, time.monotonic()
    return value
