"""Read-only monitor for the Hermes -> Twenty CRM synchronisation.

The sync itself is a separate host service (jfcrm-sync) that keeps its state in
the `jfcrm_sync` schema of this database: a capture queue (changes noticed in
Hermes), an outbox (events to send to Twenty), an inbox (events being verified),
a quarantine (items that need a person), alerts it raised, and operational
state (heartbeat, poll status, nightly reconciliation). This module only READS
those tables and turns them into plain-English health checks. It never writes,
so it cannot disturb the sync, and it degrades per section: a failure in one
query never blanks the page.

Also summarises the parsing side (email in -> parsed -> review) so one page
answers "is everything flowing?".
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Callable

from app.runtime.db import cursor

logger = logging.getLogger(__name__)

SCHEMA = "jfcrm_sync"
_CACHE_SECONDS = 45.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()

# Plain-English names for the sync's own alert codes.
ALERT_LABELS = {
    "HTTP_521": "Twenty was unreachable (web server down)",
    "REPEATED_API_FAILURES": "Repeated errors calling Twenty",
    "RETRY_AFTER_EXCEEDS_BUDGET": "Twenty asked the sync to wait longer than allowed",
    "QUEUE_BACKLOG": "Events are queuing up faster than they are sent",
    "QUARANTINE_REVIEW_REQUIRED": "An item is waiting for a person in quarantine",
    "SOURCE_REVIEW_REQUIRED": "A source record needs review",
    "UNSUPPORTED_DESTINATION_DRIFT": "Twenty's data model no longer matches what the sync expects",
    "RECONCILIATION_INTERRUPTED": "The nightly reconciliation was interrupted",
    "RECONCILIATION_DISCREPANCY": "Reconciliation found differences between Hermes and Twenty",
    "SIGNAL_SEMANTIC_COLLISION": "Two signals disagree about the same company",
    "WORKER_UNAVAILABLE": "The sync service stopped and had to restart",
    "FORBIDDEN": "Twenty refused the sync's credentials",
}


# Who should act, shown under any check that is not green.
ACTIONS = {
    "reconcile": "Developer: the nightly reconciliation job is stuck and needs to be investigated and restarted.",
    "restarts": "Developer: look at the jfcrm-sync service log on the server (it reports RUNTIME_FAILURE before each restart).",
    "processing": "Developer: confirm whether updates staying in 'processing' for days is expected.",
    "quarantine": "People: review the items in the sync's quarantine queue (Twenty review tooling).",
    "alerts": "Developer: these are the sync's own open alerts; some may be stale and need closing.",
    "poll": "Developer: the sync is deliberately slowing down. Check the send rate to Twenty.",
    "outbox": "Developer: check the send rate and any errors calling Twenty.",
    "heartbeat": "Developer: the sync is not delivering. Check the jfcrm-sync service on the server.",
    "intake": "Check the email connection (Gmail/Graph) and the Hermes worker.",
    "job": "Check the re-processing job on the Today page.",
}


def _minutes(ts: datetime | str | None) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - ts).total_seconds() / 60.0, 1)


def _iso(ts: Any) -> str | None:
    return ts.isoformat() if hasattr(ts, "isoformat") else ts


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one section must never blank the page
        logger.warning("sync monitor section failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


def _state(cur, key: str) -> dict[str, Any]:
    cur.execute(f"SELECT value FROM {SCHEMA}.operational_state WHERE key = %s", (key,))
    row = cur.fetchone()
    return (row["value"] if row else None) or {}


# ------------------------------------------------------------------ sections
def _service() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        last = _state(cur, "lastSuccessfulEvent")
        poll = _state(cur, "source-poll")
        priority = _state(cur, "company-priority")
        recon = _state(cur, "nightly-reconciliation")
        cur.execute(
            f"SELECT incident_sequence, first_seen_at, last_seen_at, active FROM {SCHEMA}.alerts "
            "WHERE code = 'WORKER_UNAVAILABLE' ORDER BY last_seen_at DESC LIMIT 1"
        )
        crash = cur.fetchone()
    return {
        "last_success_at": last.get("at"), "last_success_minutes_ago": _minutes(last.get("at")),
        "source_poll": {"status": poll.get("status"), "next_at": poll.get("nextAt"),
                        "completed_minutes_ago": _minutes(poll.get("completedAt"))},
        "company_priority": {"status": priority.get("status"), "next_at": priority.get("nextAt")},
        "reconciliation": {
            "day": recon.get("day"), "status": recon.get("status"), "checked": recon.get("checked"),
            "verified": recon.get("verified"), "exceptions": recon.get("exceptions"),
            "started_at": recon.get("startedAt"), "started_hours_ago": (_minutes(recon.get("startedAt")) or 0) / 60.0
            if recon.get("startedAt") else None,
        },
        "worker_restarts": {
            "incidents": crash["incident_sequence"] if crash else 0,
            "last_at": _iso(crash["last_seen_at"]) if crash else None,
            "last_minutes_ago": _minutes(crash["last_seen_at"]) if crash else None,
        },
    }


def _capture() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(
            f"""SELECT count(*) FILTER (WHERE processed_at IS NULL) AS pending,
                       min(captured_at) FILTER (WHERE processed_at IS NULL) AS oldest_pending,
                       count(*) FILTER (WHERE processed_at IS NULL AND last_error IS NOT NULL) AS erroring,
                       count(*) FILTER (WHERE captured_at > now() - interval '24 hours') AS captured_24h,
                       count(*) FILTER (WHERE processed_at > now() - interval '24 hours') AS processed_24h,
                       max(captured_at) AS last_captured
                FROM {SCHEMA}.capture_changes WHERE captured_at > now() - interval '3 days' OR processed_at IS NULL"""
        )
        r = cur.fetchone()
    return {"pending": r["pending"], "oldest_pending_minutes": _minutes(r["oldest_pending"]),
            "erroring": r["erroring"], "captured_24h": r["captured_24h"], "processed_24h": r["processed_24h"],
            "last_captured_minutes_ago": _minutes(r["last_captured"])}


def _outbox() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(
            f"""SELECT count(*) FILTER (WHERE status IN ('PENDING','PUBLISHING')) AS backlog,
                       min(created_at) FILTER (WHERE status IN ('PENDING','PUBLISHING')) AS oldest_backlog,
                       count(*) FILTER (WHERE status IN ('PENDING','PUBLISHING') AND attempts > 0) AS retrying,
                       count(*) FILTER (WHERE published_at > now() - interval '1 hour') AS published_1h,
                       count(*) FILTER (WHERE published_at > now() - interval '24 hours') AS published_24h,
                       count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS created_24h,
                       count(*) FILTER (WHERE last_error IS NOT NULL AND status <> 'PUBLISHED') AS with_errors,
                       max(published_at) AS last_published
                FROM {SCHEMA}.outbox WHERE created_at > now() - interval '3 days' OR status <> 'PUBLISHED'"""
        )
        r = cur.fetchone()
    return {"backlog": r["backlog"], "oldest_backlog_minutes": _minutes(r["oldest_backlog"]), "retrying": r["retrying"],
            "published_1h": r["published_1h"], "published_24h": r["published_24h"], "created_24h": r["created_24h"],
            "with_errors": r["with_errors"], "last_published_minutes_ago": _minutes(r["last_published"])}


def _inbox_and_quarantine() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(f"SELECT status, count(*) AS n FROM {SCHEMA}.inbox GROUP BY 1")
        inbox = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            f"SELECT count(*) AS n, count(*) FILTER (WHERE updated_at < now() - interval '24 hours') AS old, "
            f"min(updated_at) AS oldest FROM {SCHEMA}.inbox WHERE status = 'PROCESSING'"
        )
        proc = cur.fetchone()
        cur.execute(
            f"SELECT reason, count(*) AS n, min(created_at) AS oldest FROM {SCHEMA}.quarantine "
            "WHERE review_status = 'OPEN' GROUP BY 1 ORDER BY 2 DESC"
        )
        quarantine = [{"reason": r["reason"], "count": r["n"], "oldest_days": round((_minutes(r["oldest"]) or 0) / 1440, 1)}
                      for r in cur.fetchall()]
    return {"inbox": inbox, "processing": {"count": proc["n"], "older_than_24h": proc["old"]},
            "quarantine_open": sum(q["count"] for q in quarantine), "quarantine_by_reason": quarantine}


def _alerts() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(
            f"SELECT code, count(*) AS n, max(last_seen_at) AS last_seen, min(first_seen_at) AS first_seen "
            f"FROM {SCHEMA}.alerts WHERE active GROUP BY 1 ORDER BY max(last_seen_at) DESC"
        )
        rows = cur.fetchall()
    return {"active": [{"code": r["code"], "label": ALERT_LABELS.get(r["code"], r["code"].replace("_", " ").title()),
                        "count": r["n"], "last_seen_minutes_ago": _minutes(r["last_seen"]),
                        "since_days": round((_minutes(r["first_seen"]) or 0) / 1440, 1)} for r in rows]}


def _parsing() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(
            "SELECT max(created_at) AS last_at, "
            "count(*) FILTER (WHERE created_at > now() - interval '1 hour') AS h1, "
            "count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS h24, "
            "count(*) FILTER (WHERE created_at > now() - interval '24 hours' AND status = 'needs_review') AS review24, "
            "count(*) FILTER (WHERE created_at > now() - interval '24 hours' AND status = 'draft') AS ready24, "
            "count(*) FILTER (WHERE created_at > now() - interval '24 hours' AND status = 'spam') AS spam24 "
            "FROM drafts WHERE created_at > now() - interval '3 days'"
        )
        d = cur.fetchone()
        cur.execute(
            "SELECT status, count(*) AS n FROM intake_log WHERE recorded_at > now() - interval '24 hours' GROUP BY 1 ORDER BY 2 DESC"
        )
        intake = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT kind, status, processed_count, total_count, failed_count, updated_at FROM draft_backfill_jobs "
            "ORDER BY created_at DESC LIMIT 1"
        )
        job = cur.fetchone()
    return {
        "last_email_minutes_ago": _minutes(d["last_at"]), "parsed_1h": d["h1"], "parsed_24h": d["h24"],
        "ready_24h": d["ready24"], "needs_review_24h": d["review24"], "spam_24h": d["spam24"],
        "intake_24h": intake,
        "latest_job": ({"kind": job["kind"], "status": job["status"], "processed": job["processed_count"],
                        "total": job["total_count"], "failed": job["failed_count"],
                        "updated_minutes_ago": _minutes(job["updated_at"])} if job else None),
    }


# -------------------------------------------------------------------- checks
def _checks(s: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    def add(group: str, key: str, label: str, status: str, detail: str) -> None:
        out.append({"group": group, "id": key, "label": label, "status": status, "detail": detail})

    def ok(sec: str) -> dict[str, Any] | None:
        v = s.get(sec)
        return v if isinstance(v, dict) and "error" not in v else None

    p = ok("parsing")
    if p:
        m = p["last_email_minutes_ago"]
        if m is None or m > 360:
            add("parsing", "intake", "Emails arriving", "fail", "No new emails parsed for over 6 hours." if m else "No emails in 3 days.")
        elif m > 90:
            add("parsing", "intake", "Emails arriving", "warn", f"Last email parsed {round(m)} minutes ago.")
        else:
            add("parsing", "intake", "Emails arriving", "ok", f"{p['parsed_1h']:,} parsed in the last hour, {p['parsed_24h']:,} today.")
        job = p.get("latest_job")
        if job and job["status"] in ("running", "paused") and (job["updated_minutes_ago"] or 0) > 20 and job["status"] == "running":
            add("parsing", "job", "Re-processing", "warn", "A re-processing job has made no progress for 20+ minutes.")
        elif job and (job["failed"] or 0) > 0:
            add("parsing", "job", "Re-processing", "warn", f"The latest job had {job['failed']:,} failures.")

    svc = ok("service")
    if svc:
        m = svc["last_success_minutes_ago"]
        if m is None:
            add("twenty", "heartbeat", "Sync is delivering to Twenty", "fail", "No successful delivery recorded.")
        elif m > 60:
            add("twenty", "heartbeat", "Sync is delivering to Twenty", "fail", f"Last successful delivery was {round(m / 60, 1)} hours ago.")
        elif m > 15:
            add("twenty", "heartbeat", "Sync is delivering to Twenty", "warn", f"Last successful delivery was {round(m)} minutes ago.")
        else:
            add("twenty", "heartbeat", "Sync is delivering to Twenty", "ok", f"Last successful delivery {round(m)} minutes ago.")
        rec = svc["reconciliation"]
        hrs = rec.get("started_hours_ago")
        if rec.get("status") == "RUNNING" and hrs is not None and hrs > 36:
            add("twenty", "reconcile", "Nightly check that Hermes and Twenty match", "fail",
                f"Started {round(hrs / 24)} days ago and has not finished ({rec.get('checked') or 0} items checked). "
                "So there is no recent confirmation that the two systems agree.")
        elif rec.get("status") == "RUNNING":
            add("twenty", "reconcile", "Nightly check that Hermes and Twenty match", "ok", "Running now.")
        else:
            add("twenty", "reconcile", "Nightly check that Hermes and Twenty match", "ok", f"Last result: {rec.get('status') or 'unknown'}.")
        wr = svc["worker_restarts"]
        if wr["incidents"]:
            add("twenty", "restarts", "Sync service stability", "warn" if (wr["last_minutes_ago"] or 9e9) < 1440 else "ok",
                f"The sync service has stopped and restarted {wr['incidents']} time(s); last one "
                f"{round((wr['last_minutes_ago'] or 0) / 60, 1)} hours ago.")
        poll = svc["source_poll"]
        pm = poll.get("completed_minutes_ago")
        if pm is not None and pm > 60:
            add("twenty", "poll", "Reading changes from Hermes", "fail", f"The last read of Hermes changes finished {round(pm / 60, 1)} hours ago.")
        elif poll.get("status") == "BACKPRESSURE":
            add("twenty", "poll", "Reading changes from Hermes", "warn", "Slowing down on purpose because the send queue is full.")
        else:
            add("twenty", "poll", "Reading changes from Hermes", "ok",
                f"Last read finished {round(pm) if pm is not None else '?'} minutes ago.")

    cap = ok("capture")
    if cap:
        # NOTE: capture_changes.processed_at has not been stamped on any row since 5 Nov even though
        # updates flow normally, so "unprocessed rows" is NOT used as a health signal (it would be a
        # permanent false alarm). Activity is shown instead.
        add("twenty", "capture", "Changes noticed in Hermes", "ok" if (cap["last_captured_minutes_ago"] or 0) < 120 else "warn",
            f"{cap['captured_24h']:,} changes noticed in the last 24 hours.")

    ob = ok("outbox")
    if ob:
        m = ob["oldest_backlog_minutes"]
        rate = f"{ob['published_1h']:,} sent in the last hour"
        if ob["backlog"] and m and m > 120:
            add("twenty", "outbox", "Updates sent to Twenty", "fail", f"{ob['backlog']:,} waiting; the oldest for {round(m / 60, 1)} hours. {rate}.")
        elif ob["backlog"] and m and m > 45:
            add("twenty", "outbox", "Updates sent to Twenty", "warn", f"{ob['backlog']:,} waiting; the oldest for {round(m)} minutes. {rate}.")
        else:
            add("twenty", "outbox", "Updates sent to Twenty", "ok", f"{ob['backlog']:,} waiting. {rate}; {ob['published_24h']:,} today.")
        if ob["with_errors"]:
            add("twenty", "errors", "Send errors", "warn", f"{ob['with_errors']:,} updates have an error and are being retried.")

    iq = ok("inbox_quarantine")
    if iq:
        q = iq["quarantine_open"]
        if q:
            top = iq["quarantine_by_reason"][0]
            add("twenty", "quarantine", "Items waiting for a person", "warn",
                f"{q:,} items are in quarantine (most common: {top['reason'].replace('_', ' ').lower()}, {top['count']:,}).")
        else:
            add("twenty", "quarantine", "Items waiting for a person", "ok", "Nothing in quarantine.")
        pr = iq["processing"]
        if pr["older_than_24h"]:
            add("twenty", "processing", "Updates being verified", "warn",
                f"{pr['older_than_24h']:,} updates have been in 'processing' for over a day. A developer should confirm whether that is expected.")

    al = ok("alerts")
    if al:
        if al["active"]:
            names = "; ".join(f"{a['label']} (since {a['since_days']}d)" for a in al["active"][:4])
            add("twenty", "alerts", "Alerts raised by the sync", "warn", f"{len(al['active'])} active: {names}.")
        else:
            add("twenty", "alerts", "Alerts raised by the sync", "ok", "No active alerts.")
    return out


def build_status() -> dict[str, Any]:
    builders: dict[str, Callable[[], Any]] = {
        "parsing": _parsing, "service": _service, "capture": _capture,
        "outbox": _outbox, "inbox_quarantine": _inbox_and_quarantine, "alerts": _alerts,
    }
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="hermes-sync") as pool:
        futures = {k: pool.submit(_safe, fn) for k, fn in builders.items()}
        sections = {k: f.result() for k, f in futures.items()}
    checks = _checks(sections)
    for c in checks:
        if c["status"] != "ok" and c["id"] in ACTIONS:
            c["action"] = ACTIONS[c["id"]]
    rank = {"ok": 0, "warn": 1, "fail": 2}
    overall = {g: max((rank[c["status"]] for c in checks if c["group"] == g), default=0) for g in ("parsing", "twenty")}
    names = {0: "ok", 1: "warn", 2: "fail"}
    return {"generated_at": datetime.now(UTC).isoformat(), "checks": checks,
            "overall": {g: names[v] for g, v in overall.items()}, **sections}


def get_status(force: bool = False) -> dict[str, Any]:
    with _lock:
        if not force and _cache["value"] is not None and time.monotonic() - _cache["at"] < _CACHE_SECONDS:
            return _cache["value"]
    value = build_status()
    with _lock:
        _cache["value"], _cache["at"] = value, time.monotonic()
    return value
