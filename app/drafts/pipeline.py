"""Job-posting pipeline health: how much of the parsed job-requirement flow is
complete enough to become a Jobfynder Core job, and where it is not.

Read-only. "Ready" is the minimum Core's POST /hermes/job/create needs for a
usable DRAFT job: a title, an employment type (Core's one hard requirement),
a location, at least one required skill and a recruiter email to attribute it
to. Exact duplicates (metadata.exact_content_duplicate_of) are excluded, as
in the review list.
"""

from __future__ import annotations

from typing import Any

from app.runtime.db import cursor

_REC = "d.payload->'structured_data'->'email_parsing'->'records'->0"

# field -> SQL predicate "has a usable value"
_FIELDS: dict[str, str] = {
    "job_title": f"coalesce({_REC}->>'job_title','') <> ''",
    "company": f"coalesce({_REC}->>'company','') <> ''",
    "location": f"coalesce({_REC}->>'location','') <> ''",
    "employment_type": f"coalesce({_REC}->>'employment_type','') <> ''",
    "required_skills": f"jsonb_array_length(coalesce({_REC}->'required_skills','[]'::jsonb)) > 0",
    "rate": f"(coalesce({_REC}->>'rate_or_salary','') <> '' OR {_REC}->>'rate_min' IS NOT NULL)",
    "work_authorization": f"coalesce({_REC}->>'work_authorization','') <> ''",
    "years_of_experience": f"{_REC}->>'years_of_experience' IS NOT NULL",
    "work_mode": f"coalesce({_REC}->>'work_mode','') <> ''",
    "duration": f"coalesce({_REC}->>'duration','') <> ''",
    "recruiter_email": "coalesce(d.metadata->'sender'->>'email', d.metadata->'original_sender_candidate'->>'email', '') <> ''",
}
_READY = " AND ".join(f"({_FIELDS[k]})" for k in ("job_title", "employment_type", "location", "required_skills", "recruiter_email"))


def get_pipeline_stats(days: int = 14) -> dict[str, Any]:
    days = max(1, min(int(days), 90))
    base = (
        "d.draft_type = 'draft_job_requirement' "
        "AND d.status IN ('draft','needs_review') "
        "AND d.created_at > now() - make_interval(days => %(days)s) "
        "AND d.metadata->>'exact_content_duplicate_of' IS NULL"
    )
    select_fields = ", ".join(
        f"count(*) FILTER (WHERE {pred}) AS f_{name}" for name, pred in _FIELDS.items()
    )
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '30s'")
        cur.execute(
            f"""SELECT count(*) AS total,
                       count(*) FILTER (WHERE {_READY}) AS ready,
                       {select_fields}
                FROM drafts d WHERE {base}""",
            {"days": days},
        )
        row = cur.fetchone()
        # What is the single most common missing piece among not-ready posts?
        blockers: dict[str, int] = {}
        for name in ("job_title", "employment_type", "location", "required_skills", "recruiter_email"):
            cur.execute(
                f"""SELECT count(*) AS n FROM drafts d
                    WHERE {base} AND NOT ({_FIELDS[name]})""",
                {"days": days},
            )
            blockers[name] = cur.fetchone()["n"]
        cur.execute(
            f"""SELECT count(*) AS n FROM drafts d WHERE {base}
                AND NOT ({_FIELDS['employment_type']})
                AND ({_FIELDS['job_title']}) AND ({_FIELDS['location']})
                AND ({_FIELDS['required_skills']}) AND ({_FIELDS['recruiter_email']})""",
            {"days": days},
        )
        only_employment_type_missing = cur.fetchone()["n"]
        cur.execute("SELECT status, count(*) AS n FROM core_pushes GROUP BY status")
        pushes = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT left(error, 120) AS error, count(*) AS n FROM core_pushes WHERE status='failed' GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
        )
        push_errors = cur.fetchall()
        cur.execute(
            "SELECT count(*) AS n FROM drafts WHERE draft_type='draft_job_requirement' AND status='published'"
        )
        published = cur.fetchone()["n"]

    total = row["total"] or 0

    def pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    return {
        "window_days": days,
        "considered": total,
        "ready_for_core": row["ready"],
        "ready_pct": pct(row["ready"]),
        "only_employment_type_missing": only_employment_type_missing,
        "fill_rates_pct": {name: pct(row[f"f_{name}"]) for name in _FIELDS},
        "missing_by_blocker": blockers,
        "published_in_hermes": published,
        "core_pushes": pushes,
        "core_push_top_errors": push_errors,
        **_dedup_and_outbox(),
    }


def _dedup_and_outbox() -> dict[str, Any]:
    from app.drafts.job_dedup import get_cluster_stats
    from app.integrations.core_outbox import get_outbox_stats

    return {"clusters": get_cluster_stats(), "outbox": get_outbox_stats()}
