"""Aggregate read-only reporting data for the Hermes admin dashboard
and the natural-language assistant (app/assistant/service.py) -- both
surfaces call these SAME functions, so a number on the dashboard and
the answer to the same question asked in chat can never disagree.

Every function here is read-only and safe to call freely: no writes,
no side effects, bounded query windows (never an unbounded table scan
over the full history).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from app.runtime.db import cursor
from app.understanding.taxonomy.candidates import _MIN_BOILERPLATE_DISTINCT_SENDERS
from app.understanding.taxonomy.loader import get_canonical_skill_entries, get_job_title_entries

# Automated reviewers -- distinguishes "the daily triage job cleared
# this" from "a person clicked Approve/Reject" in activity reporting.
# Kept as a prefix match (not an exact set) so a future automated
# reviewer name doesn't need this list updated to be recognized as
# automated, as long as it follows the same "hermes-"/"claude-" naming.
_AUTOMATED_REVIEWER_PREFIXES = ("hermes-", "claude-")


def _is_automated_reviewer(reviewed_by: str | None) -> bool:
    if not reviewed_by:
        return False
    return reviewed_by.startswith(_AUTOMATED_REVIEWER_PREFIXES)


def get_taxonomy_overview() -> dict[str, Any]:
    """Current canonical taxonomy size, plus how much of it was added
    in the last 7/30 days (measured by candidate-approval timestamps,
    since the canonical JSON files themselves don't carry an add-date
    per entry -- taxonomy_candidates.reviewed_at is the source of
    truth for "when was this added").
    """
    total_skills = len(get_canonical_skill_entries())
    total_titles = len(get_job_title_entries())

    now = datetime.now(UTC)
    with cursor() as cur:
        cur.execute(
            "SELECT signal_type, "
            "COUNT(*) FILTER (WHERE reviewed_at >= %s) AS added_7d, "
            "COUNT(*) FILTER (WHERE reviewed_at >= %s) AS added_30d "
            "FROM taxonomy_candidates "
            "WHERE status = 'approved' AND signal_type IN ('skill', 'job_title') "
            "GROUP BY signal_type",
            (now - timedelta(days=7), now - timedelta(days=30)),
        )
        rows = {r["signal_type"]: r for r in cur.fetchall()}

    return {
        "total_skills": total_skills,
        "total_job_titles": total_titles,
        "skills_added_7d": rows.get("skill", {}).get("added_7d", 0),
        "skills_added_30d": rows.get("skill", {}).get("added_30d", 0),
        "job_titles_added_7d": rows.get("job_title", {}).get("added_7d", 0),
        "job_titles_added_30d": rows.get("job_title", {}).get("added_30d", 0),
    }


def get_candidate_queue_health() -> dict[str, Any]:
    """Current backlog by signal type, plus the oldest pending item's
    age -- a growing "oldest pending" age is the clearest single signal
    that the daily triage job has stopped keeping up, before the raw
    pending count alone would make that obvious.

    boilerplate_line rows get the SAME distinct_senders >= _MIN_
    BOILERPLATE_DISTINCT_SENDERS filter list_taxonomy_candidates
    already applies (see app/understanding/taxonomy/candidates.py) --
    every distinct line seen gets its own row cheaply, most from a
    single company's own one-off content and never meant to be
    reviewed. Counting those raw rows here first showed a "37,362
    pending boilerplate" backlog that didn't actually exist -- the real,
    reviewable count was 6. Not filtering here would've meant the
    dashboard and the assistant both confidently reporting a false
    incident.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT signal_type, COUNT(*) AS pending_count, MIN(first_seen_at) AS oldest_first_seen "
            "FROM taxonomy_candidates "
            "WHERE status = 'pending' "
            "AND (signal_type != 'boilerplate_line' OR jsonb_array_length(distinct_senders) >= %s) "
            "GROUP BY signal_type",
            (_MIN_BOILERPLATE_DISTINCT_SENDERS,),
        )
        rows = {r["signal_type"]: r for r in cur.fetchall()}

    now = datetime.now(UTC)

    def _entry(signal_type: str) -> dict[str, Any]:
        row = rows.get(signal_type)
        if not row:
            return {"pending_count": 0, "oldest_pending_days": 0}
        oldest = row["oldest_first_seen"]
        age_days = (now - oldest).days if oldest else 0
        return {"pending_count": row["pending_count"], "oldest_pending_days": age_days}

    return {
        "skill": _entry("skill"),
        "job_title": _entry("job_title"),
        "boilerplate_line": _entry("boilerplate_line"),
    }


def get_triage_activity(days: int = 14) -> list[dict[str, Any]]:
    """Daily approved/rejected counts, split automated (the daily
    triage job / a bulk-cleanup pass) vs human (a reviewer clicking
    Approve/Reject in the UI), for the last `days` days. Ordered oldest
    to newest, one row per calendar day that had at least one review
    (a quiet day is simply absent, not a zero-row) -- callers that need
    every day represented (a chart x-axis) fill the gaps themselves.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            "SELECT reviewed_at::date AS day, status, reviewed_by "
            "FROM taxonomy_candidates "
            "WHERE reviewed_at >= %s AND status IN ('approved', 'rejected')",
            (since,),
        )
        rows = cur.fetchall()

    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        day_key = row["day"].isoformat()
        bucket = by_day.setdefault(
            day_key, {"approved_automated": 0, "approved_human": 0, "rejected_automated": 0, "rejected_human": 0}
        )
        automated = _is_automated_reviewer(row["reviewed_by"])
        field = f"{row['status']}_{'automated' if automated else 'human'}"
        bucket[field] += 1

    return [{"date": day, **counts} for day, counts in sorted(by_day.items())]


def get_llm_cost_trend(days: int = 30) -> dict[str, Any]:
    """Daily LLM spend for the last `days` days, pulled live from the
    Langfuse Daily Metrics API (self-hosted -- see LANGFUSE_BASE_URL).
    Returns an empty trend (never raises) if Langfuse isn't configured
    or unreachable -- cost reporting is a nice-to-have overlay, not
    something that should ever break the rest of the dashboard.
    """
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    base = os.getenv("LANGFUSE_BASE_URL")
    if not (pub and sec and base):
        return {"available": False, "days": []}

    auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
    # Langfuse sits behind Cloudflare here, which blocks requests with
    # no browser-shaped User-Agent (observed directly: identical request
    # minus this header gets a bare Cloudflare 403, error code 1010).
    req = urllib.request.Request(
        f"{base}/api/public/metrics/daily?limit=100",
        headers={"Authorization": f"Basic {auth}", "User-Agent": "Mozilla/5.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {"available": False, "days": []}

    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    today = datetime.now(UTC).date().isoformat()
    rows = [
        {"date": r["date"], "cost": round(r.get("totalCost", 0.0), 4), "traces": r.get("countTraces", 0)}
        for r in data.get("data", [])
        # Langfuse's own seed/test data includes at least one row with a
        # date far in the future (observed: "2105-01-05") -- excluded by
        # requiring the date fall between the cutoff and today.
        if cutoff <= r["date"] <= today
    ]
    rows.sort(key=lambda r: r["date"])

    return {
        "available": True,
        "days": rows,
        "total_cost": round(sum(r["cost"] for r in rows), 4),
    }


def get_parsing_quality(days: int = 7) -> dict[str, Any]:
    """Recent draft volume and confidence distribution -- the same
    "is parsing actually working" signal a human would eyeball the
    review queue for, summarized instead of scrolled through.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            "SELECT draft_type, status, confidence, requires_review "
            "FROM drafts WHERE created_at >= %s",
            (since,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"total_drafts": 0, "avg_confidence": None, "needs_review_pct": None, "by_type": {}}

    total = len(rows)
    needs_review = sum(1 for r in rows if r["requires_review"])
    avg_confidence = sum(r["confidence"] or 0.0 for r in rows) / total

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["draft_type"]] = by_type.get(r["draft_type"], 0) + 1

    return {
        "total_drafts": total,
        "avg_confidence": round(avg_confidence, 3),
        "needs_review_pct": round(100 * needs_review / total, 1),
        "by_type": by_type,
    }


def get_dashboard_overview() -> dict[str, Any]:
    """Everything the dashboard page needs in one call."""
    return {
        "taxonomy": get_taxonomy_overview(),
        "queue_health": get_candidate_queue_health(),
        "triage_activity": get_triage_activity(days=14),
        "llm_cost": get_llm_cost_trend(days=30),
        "parsing_quality": get_parsing_quality(days=7),
        "generated_at": datetime.now(UTC).isoformat(),
    }
