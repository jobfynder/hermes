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
from app.understanding.taxonomy.candidates import (
    _MIN_BOILERPLATE_DISTINCT_SENDERS,
    _is_noise_job_title,
    _is_noise_skill_term,
)
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


# field_provenance.extractor values that mean "an LLM prompt ran for
# this field" (app/email_parsing/llm_fallback.py) -- as opposed to
# hermes_email_deterministic_parser / hermes_email_signature_parser,
# which never call an LLM. A draft with ANY row using one of these is
# "AI-assisted"; a draft with none is "parser-only".
_AI_EXTRACTORS = ("jf.jobs.jd.extract", "jf.broadcast.hotlist.extract")


def get_ingestion_health(days: int = 1) -> dict[str, Any]:
    """What actually arrived and what happened to it, from intake_log --
    the first thing anything else here depends on being healthy.
    received/parsed/duplicate are the only statuses intake_log
    currently records (see app/channels/service.py:process_channel_
    intake) -- there is deliberately no separate "failed" bucket
    reported here, since one doesn't exist in the data; an intake
    exception surfaces as a gap between received and parsed instead,
    which processing_rate_pct below makes visible.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            "SELECT status, channel, COUNT(*) AS n "
            "FROM intake_log WHERE recorded_at >= %s GROUP BY status, channel",
            (since,),
        )
        rows = cur.fetchall()

    by_status: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + row["n"]
        # Only "received" counts toward inbound volume by channel --
        # each message also gets a "parsed" (and sometimes "duplicate")
        # row later for the SAME message, so summing every status here
        # would silently double- or triple-count actual email volume.
        if row["status"] == "received":
            by_channel[row["channel"]] = by_channel.get(row["channel"], 0) + row["n"]

    received = by_status.get("received", 0)
    parsed = by_status.get("parsed", 0)
    duplicate = by_status.get("duplicate", 0)
    hours = max(days * 24, 1)

    return {
        "days": days,
        "received": received,
        "parsed": parsed,
        "duplicate": duplicate,
        "unaccounted": max(0, received - parsed - duplicate),
        "processing_rate_pct": round(100 * parsed / received, 1) if received else None,
        "received_per_hour": round(received / hours, 1),
        "by_channel": by_channel,
    }


def get_classification_report(days: int = 7) -> dict[str, Any]:
    """How incoming mail got classified -- draft_type counts and average
    confidence per type, plus a daily trend for spotting a sudden shift
    (a mailbox misconfiguration, a new relay showing up) at a glance.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            "SELECT draft_type, created_at::date AS day, confidence "
            "FROM drafts WHERE created_at >= %s",
            (since,),
        )
        rows = cur.fetchall()

    by_type: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_type.setdefault(row["draft_type"], {"count": 0, "confidence_sum": 0.0})
        bucket["count"] += 1
        bucket["confidence_sum"] += row["confidence"] or 0.0

        day_key = row["day"].isoformat()
        day_bucket = by_day.setdefault(day_key, {})
        day_bucket[row["draft_type"]] = day_bucket.get(row["draft_type"], 0) + 1

    total = sum(b["count"] for b in by_type.values())
    types = [
        {
            "draft_type": t,
            "count": b["count"],
            "pct_of_total": round(100 * b["count"] / total, 1) if total else None,
            "avg_confidence": round(b["confidence_sum"] / b["count"], 3) if b["count"] else None,
        }
        for t, b in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])
    ]

    return {
        "days": days,
        "total": total,
        "by_type": types,
        "daily": [{"date": d, **counts} for d, counts in sorted(by_day.items())],
    }


def get_ai_dependency_report(days: int = 7) -> dict[str, Any]:
    """What share of drafts needed an LLM call at all, and what the LLM
    cost looked like over the same window -- the two numbers this
    exists to keep an eye on together: if AI-assisted % creeps up
    without a corresponding reason (a new hard-to-parse vendor
    template, say), cost will follow it up.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            """
            SELECT d.draft_id,
                   bool_or(fp.extractor = ANY(%s)) AS ai_used
            FROM drafts d
            LEFT JOIN field_provenance fp ON fp.parse_run_id = d.draft_id::text
            WHERE d.created_at >= %s
            GROUP BY d.draft_id
            """,
            (list(_AI_EXTRACTORS), since),
        )
        rows = cur.fetchall()

    total = len(rows)
    ai_assisted = sum(1 for r in rows if r["ai_used"])
    parser_only = total - ai_assisted

    cost = get_llm_cost_trend(days=days)

    return {
        "days": days,
        "total_drafts": total,
        "parser_only_count": parser_only,
        "ai_assisted_count": ai_assisted,
        "parser_only_pct": round(100 * parser_only / total, 1) if total else None,
        "ai_assisted_pct": round(100 * ai_assisted / total, 1) if total else None,
        "llm_cost": cost,
        "cost_per_1000_drafts": (
            round(1000 * cost["total_cost"] / total, 2) if total and cost.get("available") else None
        ),
    }


def get_review_queue_report(days: int = 7) -> dict[str, Any]:
    """Current drafts by status, plus WHY the ones needing review need
    it -- the record-level warning codes (app/email_parsing/parsers.py:
    _score_requirement_record) are the actual, specific reason a
    reviewer has to look at it, not just a blanket "low confidence".
    """
    with cursor() as cur:
        cur.execute("SELECT status, COUNT(*) AS n FROM drafts GROUP BY status")
        status_counts = {r["status"]: r["n"] for r in cur.fetchall()}

        since = datetime.now(UTC) - timedelta(days=days)
        cur.execute(
            """
            SELECT w.value AS reason, COUNT(*) AS n
            FROM drafts d,
                 jsonb_array_elements(d.payload -> 'structured_data' -> 'email_parsing' -> 'records') rec,
                 jsonb_array_elements_text(rec -> 'warnings') w(value)
            WHERE d.created_at >= %s
            GROUP BY w.value
            ORDER BY n DESC
            """,
            (since,),
        )
        reasons = [{"reason": r["reason"], "count": r["n"]} for r in cur.fetchall()]

    return {
        "days": days,
        "by_status": status_counts,
        "review_reasons": reasons,
    }


def get_signature_quality_report(days: int = 30) -> dict[str, Any]:
    """Per-signature-field fill rate, precision (measured from actual
    reviewer corrections, not just stated confidence), false-positive
    rate, and confidence calibration -- see app/drafts/accuracy.py.

    Important caveat surfaced here, not hidden: a field with zero
    recorded corrections shows as 100% precision, but that can mean
    either "genuinely always correct" or "nobody has been correcting
    it" -- this function can't tell those apart on its own. A field
    with high fill volume, low average confidence, AND zero corrections
    is the pattern worth a manual spot-check rather than trusting the
    100% at face value.
    """
    from app.drafts.accuracy import compute_accuracy_summary

    summary = compute_accuracy_summary(days=days)
    fields = summary["signature_fields"]

    for f in fields:
        f["needs_spot_check"] = (
            f["filled_count"] >= 100
            and f["corrected_wrong_count"] == 0
            and (f["avg_stated_confidence"] or 100) < 85
        )

    return {"days": days, "fields": fields}


def get_recruitment_intelligence(days: int = 30, limit: int = 15) -> dict[str, Any]:
    """What's actually in the postings coming through Hermes -- turns
    ingestion into Jobfynder market intelligence rather than just a
    parsing-health signal.

    top_skills comes from skill_usage_stats, which is a cumulative
    all-time counter (no per-day breakdown exists in that table), so it
    deliberately ignores `days` -- documented via all_time=True rather
    than silently pretending it's windowed. It also filters through the
    SAME _is_noise_skill_term() check the daily triage job uses: a
    canonical taxonomy entry approved before that filter existed can
    still be junk (caught here first-hand -- "https" was the single
    most-tracked "skill" at ~4,950 occurrences, a URL-scheme fragment
    that slipped through as a taxonomy candidate before the noise
    filter was added). Filtering here fixes what the report SHOWS
    without touching the canonical taxonomy file itself.

    Everything else (job titles, locations, employment type, work
    authorization, rate presence) is windowed by `days` and pulled from
    job_requirement records, the actual structured postings.

    top_job_titles also filters through _is_noise_job_title(), but that
    check only catches structurally-malformed candidate strings
    (fragments, verb phrases, encoding artifacts) -- it does NOT catch a
    single real word that's simply the wrong classification. Real
    production data hit exactly that: "DATA", "Contract", "AI",
    "ServiceNow", and "Mobile" were ranking as top "titles" -- not a
    classifier bug (extract_taxonomy_signals only ever matches literal
    canonical-taxonomy entries), but five bad entries a human reviewer
    approved into job_titles.json through the ordinary candidate-review
    flow. Root-caused via bulk_delete_job_titles() (app/understanding/
    taxonomy/loader.py) rather than filtered here -- deleting the
    canonical entries stops future emails from matching them too, not
    just this report's display. Drafts parsed BEFORE the deletion keep
    their already-stored normalized_job_titles as a historical snapshot
    (correct: that's genuinely what got extracted from them at the
    time), so a few historical drafts may still surface here even
    though the taxonomy is now clean.
    """
    skill_rows = []
    with cursor() as cur:
        cur.execute(
            "SELECT skill_name, times_seen FROM skill_usage_stats ORDER BY times_seen DESC LIMIT %s",
            (limit * 3,),  # over-fetch since some will be filtered as noise
        )
        for r in cur.fetchall():
            if not _is_noise_skill_term(r["skill_name"]):
                skill_rows.append({"skill": r["skill_name"], "times_seen": r["times_seen"]})
            if len(skill_rows) >= limit:
                break

        since = datetime.now(UTC) - timedelta(days=days)
        cur.execute(
            "SELECT title.value AS title, COUNT(*) AS n "
            "FROM drafts d, jsonb_array_elements_text(d.normalized_job_titles) title "
            "WHERE d.created_at >= %s AND jsonb_array_length(d.normalized_job_titles) > 0 "
            "GROUP BY title.value ORDER BY n DESC LIMIT %s",
            (since, limit * 3),  # over-fetch since some will be filtered as noise
        )
        top_job_titles = []
        for r in cur.fetchall():
            if not _is_noise_job_title(r["title"]):
                top_job_titles.append({"title": r["title"], "count": r["n"]})
            if len(top_job_titles) >= limit:
                break

        cur.execute(
            """
            SELECT rec->>'location' AS location,
                   rec->>'employment_type' AS employment_type,
                   rec->>'work_authorization' AS work_authorization,
                   rec->>'rate_or_salary' AS rate_or_salary
            FROM drafts d,
                 jsonb_array_elements(d.payload -> 'structured_data' -> 'email_parsing' -> 'records') rec
            WHERE d.draft_type = 'draft_job_requirement' AND d.created_at >= %s
            """,
            (since,),
        )
        record_rows = cur.fetchall()

    def _top_counts(field: str, n: int = limit) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in record_rows:
            value = (row[field] or "").strip()
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:n]
        return [{"value": v, "count": c} for v, c in ranked]

    total_records = len(record_rows)
    rate_specified = sum(1 for r in record_rows if (r["rate_or_salary"] or "").strip())

    return {
        "days": days,
        "top_skills": skill_rows,
        "top_skills_all_time": True,
        "top_job_titles": top_job_titles,
        "top_locations": _top_counts("location"),
        "top_employment_types": _top_counts("employment_type"),
        "top_work_authorizations": _top_counts("work_authorization"),
        "total_job_records": total_records,
        "rate_specified_count": rate_specified,
        "rate_specified_pct": round(100 * rate_specified / total_records, 1) if total_records else None,
    }


def get_sender_intelligence(days: int = 30, limit: int = 15) -> dict[str, Any]:
    """Begins building recruiter/company relationship intelligence: who
    is actually sending Hermes postings, how much of it is jobs vs
    hotlists, how reliable each sender's parses are, and how much of
    their volume is exact-content resends rather than new postings.

    Duplicate detection reuses metadata.exact_content_duplicate_of (set
    in app/channels/service.py at intake time, when a draft's content
    exactly matches an earlier draft's) rather than inventing a new
    definition of "duplicate" here.

    Grouped by sender email address, with a separate domain-level
    rollup (the same recruiter often sends from more than one mailbox
    at the same company).
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            "SELECT metadata -> 'sender' ->> 'email' AS sender_email, "
            "draft_type, confidence, "
            "(metadata ->> 'exact_content_duplicate_of') IS NOT NULL AS is_duplicate "
            "FROM drafts WHERE created_at >= %s",
            (since,),
        )
        rows = cur.fetchall()

    by_sender: dict[str, dict[str, Any]] = {}
    by_domain: dict[str, dict[str, Any]] = {}

    for row in rows:
        email = (row["sender_email"] or "").strip().lower()
        if not email or "@" not in email:
            continue
        domain = email.split("@")[-1]

        for bucket_map, key in ((by_sender, email), (by_domain, domain)):
            bucket = bucket_map.setdefault(
                key, {"total": 0, "jobs": 0, "hotlists": 0, "confidence_sum": 0.0, "duplicates": 0}
            )
            bucket["total"] += 1
            if row["draft_type"] == "draft_job_requirement":
                bucket["jobs"] += 1
            elif row["draft_type"] == "draft_hotlist":
                bucket["hotlists"] += 1
            bucket["confidence_sum"] += row["confidence"] or 0.0
            if row["is_duplicate"]:
                bucket["duplicates"] += 1

    def _rank(bucket_map: dict[str, dict[str, Any]], id_field: str) -> list[dict[str, Any]]:
        ranked = sorted(bucket_map.items(), key=lambda kv: -kv[1]["total"])[:limit]
        return [
            {
                id_field: key,
                "total_drafts": b["total"],
                "jobs": b["jobs"],
                "hotlists": b["hotlists"],
                "other": b["total"] - b["jobs"] - b["hotlists"],
                "avg_confidence": round(b["confidence_sum"] / b["total"], 3) if b["total"] else None,
                "duplicate_count": b["duplicates"],
                "duplicate_pct": round(100 * b["duplicates"] / b["total"], 1) if b["total"] else None,
            }
            for key, b in ranked
        ]

    return {
        "days": days,
        "total_senders": len(by_sender),
        "total_domains": len(by_domain),
        "top_senders": _rank(by_sender, "sender_email"),
        "top_domains": _rank(by_domain, "domain"),
    }


def get_today_summary() -> dict[str, Any]:
    """The single top-of-dashboard KPI bar: today's ingestion,
    classification, parsing, and review-queue snapshot in one call.
    """
    ingestion = get_ingestion_health(days=1)
    classification = get_classification_report(days=1)
    ai = get_ai_dependency_report(days=1)
    quality = get_parsing_quality(days=1)

    type_counts = {t["draft_type"]: t["count"] for t in classification["by_type"]}

    return {
        "emails_received": ingestion["received"],
        "jobs": type_counts.get("draft_job_requirement", 0),
        "hotlists": type_counts.get("draft_hotlist", 0),
        "other": classification["total"] - type_counts.get("draft_job_requirement", 0) - type_counts.get("draft_hotlist", 0),
        "processing_rate_pct": ingestion["processing_rate_pct"],
        "needs_review_pct": quality["needs_review_pct"],
        "parser_only_pct": ai["parser_only_pct"],
        "ai_assisted_pct": ai["ai_assisted_pct"],
        "avg_confidence": quality["avg_confidence"],
    }


def get_dashboard_overview() -> dict[str, Any]:
    """Everything the dashboard page needs in one call."""
    return {
        "today": get_today_summary(),
        "taxonomy": get_taxonomy_overview(),
        "queue_health": get_candidate_queue_health(),
        "triage_activity": get_triage_activity(days=14),
        "llm_cost": get_llm_cost_trend(days=30),
        "parsing_quality": get_parsing_quality(days=7),
        "ingestion_health": get_ingestion_health(days=7),
        "classification": get_classification_report(days=7),
        "ai_dependency": get_ai_dependency_report(days=7),
        "review_queue": get_review_queue_report(days=7),
        "signature_quality": get_signature_quality_report(days=30),
        "recruitment_intelligence": get_recruitment_intelligence(days=30),
        "sender_intelligence": get_sender_intelligence(days=30),
        "generated_at": datetime.now(UTC).isoformat(),
    }
