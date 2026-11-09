"""Fill a missing employment type from the sender's own history.

Most unlabelled job emails carry no employment-type wording at all (measured:
77% of the still-empty posts). But a given recruiter or vendor almost always
posts the same kind of work: on 60 days of production data, a sender with >= 8
posts that state a type, >= 90% of them the same, predicts the type of their
unlabelled posts with 95.5% agreement (leave-one-out), and covers ~60% of the
remaining blanks.

Safety, in order of importance:
  * Priors are learned ONLY from stated values (no inferred basis), so a guess
    can never become evidence for the next guess.
  * Fill-only: a post that already has a type is never touched; a post a human
    has edited is never touched.
  * Every fill is flagged employment_type_basis = 'sender_history' so reviewers
    and Core can tell it from an extracted value.
  * Kill switch: HERMES_EMPLOYMENT_PRIORS_ENABLED=0.
Pure SQL, no model calls.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.runtime.db import cursor

logger = logging.getLogger(__name__)

MIN_POSTS = 8
MIN_SHARE = 0.90
WINDOW_DAYS = 60
REFRESH_HOURS = 12

_REC = "r.rec"
_LATERAL = "CROSS JOIN LATERAL (SELECT d.payload->'structured_data'->'email_parsing'->'records'->0 AS rec OFFSET 0) r"

# Coarse class of a stated value, mirroring Core's employment types.
_CLASS_SQL = """CASE
  WHEN @@ ~* 'contract[ -]*to[ -]*(hire|perm)|c2h|cth' THEN 'Contract to Hire'
  WHEN @@ ~* 'part' THEN 'Part-time'
  WHEN @@ ~* 'full|perm|fte|direct' THEN 'Full-time'
  WHEN @@ ~* 'contract|c2c|w-?2|1099|corp|temp|consult|freelance' THEN 'Contract'
END"""


def enabled() -> bool:
    return os.getenv("HERMES_EMPLOYMENT_PRIORS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def refresh_priors(days: int = WINDOW_DAYS, min_posts: int = MIN_POSTS, min_share: float = MIN_SHARE) -> dict[str, Any]:
    """Rebuild the per-sender table from recent STATED values."""
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '240s'")
        cur.execute(
            f"""
            WITH stated AS (
              SELECT lower(d.metadata->'sender'->>'email') AS sender_key,
                     {_CLASS_SQL.replace('@@', '(' + _REC + "->>'employment_type')")} AS cls
              FROM drafts d {_LATERAL}
              WHERE d.draft_type = 'draft_job_requirement'
                AND d.created_at > now() - make_interval(days => %(days)s)
                AND coalesce(d.metadata->'sender'->>'email', '') <> ''
                AND coalesce({_REC}->>'employment_type', '') <> ''
                AND coalesce({_REC}->>'employment_type_basis', 'label') IN ('label', 'keyword')
            ), counted AS (
              SELECT sender_key, cls, count(*) AS n FROM stated WHERE cls IS NOT NULL GROUP BY 1, 2
            ), ranked AS (
              SELECT sender_key, cls, n, sum(n) OVER (PARTITION BY sender_key) AS total,
                     row_number() OVER (PARTITION BY sender_key ORDER BY n DESC) AS rk
              FROM counted
            ), fresh AS (
              SELECT sender_key, cls AS employment_type, total::int AS stated_count, (n::float / total)::real AS share
              FROM ranked WHERE rk = 1 AND total >= %(min_posts)s AND n::float / total >= %(min_share)s
            ), upserted AS (
              INSERT INTO sender_employment_priors AS p (sender_key, employment_type, stated_count, share, updated_at)
              SELECT sender_key, employment_type, stated_count, share, now() FROM fresh
              ON CONFLICT (sender_key) DO UPDATE SET employment_type = EXCLUDED.employment_type,
                stated_count = EXCLUDED.stated_count, share = EXCLUDED.share, updated_at = now()
              RETURNING 1
            ), pruned AS (
              DELETE FROM sender_employment_priors p WHERE NOT EXISTS (SELECT 1 FROM fresh f WHERE f.sender_key = p.sender_key)
              RETURNING 1
            )
            SELECT (SELECT count(*) FROM upserted) AS upserted, (SELECT count(*) FROM pruned) AS pruned
            """,
            {"days": days, "min_posts": min_posts, "min_share": min_share},
        )
        row = cur.fetchone()
    return {"upserted": row["upserted"], "pruned": row["pruned"]}


def priors_age_hours() -> float | None:
    with cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM (now() - max(updated_at))) / 3600 AS h FROM sender_employment_priors")
        h = cur.fetchone()["h"]
    return float(h) if h is not None else None


def fill_from_priors(batch: int = 300, days: int = 30) -> dict[str, Any]:
    """Fill up to `batch` live job posts whose type is empty and whose sender
    has a strong prior. Returns {'filled': n}."""
    with cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '60s'")
        cur.execute(
            f"""
            WITH todo AS (
              SELECT d.draft_id, p.employment_type
              FROM drafts d {_LATERAL}
              JOIN sender_employment_priors p ON p.sender_key = lower(d.metadata->'sender'->>'email')
              WHERE d.draft_type = 'draft_job_requirement'
                AND d.status IN ('draft', 'needs_review')
                AND d.created_at > now() - make_interval(days => %(days)s)
                AND coalesce({_REC}->>'employment_type', '') = ''
                AND jsonb_typeof(d.payload->'structured_data'->'email_parsing'->'records'->0) = 'object'
                AND NOT EXISTS (SELECT 1 FROM field_provenance fp
                                WHERE fp.parse_run_id = d.draft_id::text
                                  AND fp.extractor IN ('recruiter_correction', 'reviewer_correction'))
              ORDER BY d.created_at DESC
              LIMIT %(batch)s
              FOR UPDATE OF d SKIP LOCKED
            )
            UPDATE drafts d SET payload = jsonb_set(
                jsonb_set(d.payload, '{{structured_data,email_parsing,records,0,employment_type}}', to_jsonb(todo.employment_type), true),
                '{{structured_data,email_parsing,records,0,employment_type_basis}}', '"sender_history"', true)
            FROM todo WHERE d.draft_id = todo.draft_id
            RETURNING d.draft_id
            """,
            {"days": days, "batch": batch},
        )
        filled = len(cur.fetchall())
    return {"filled": filled}


def run_step(batch: int = 300) -> dict[str, Any]:
    """One scheduler tick: refresh the priors when stale, then fill a batch."""
    if not enabled():
        return {"enabled": False}
    out: dict[str, Any] = {}
    age = priors_age_hours()
    if age is None or age >= REFRESH_HOURS:
        out["refresh"] = refresh_priors()
    out.update(fill_from_priors(batch))
    return out
