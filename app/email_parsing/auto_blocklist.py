"""Automatic sender blocklist for the clear-cut cases.

Measured on 60 days of production job requirements: spam is rare (4 posts in
30 days) and only a handful of senders are pure noise, so blocking is a
small, precise lever -- the rules therefore err hard on the side of NOT
blocking. A blocked sender never reaches intake, so a false positive costs
real postings.

* Domain: not a shared/free-mail domain, >= 20 job posts in 60 days, none of
  them usable (draft/published) and none published ever.
* Address (free-mail senders only): >= 8 posts in 60 days, none usable, and
  >= 5 of them rejected by a reviewer (duplicate rejections do not count).

Capped per run, reason starts with "auto:", fully reversible from the
blocklist screen. Existing blocks are never modified.
"""

from __future__ import annotations

import os
from typing import Any

from app.companies.service import SHARED_DOMAINS
from app.email_parsing.blocklist import add_block
from app.runtime.db import cursor

DOMAIN_MIN_POSTS = 20
ADDRESS_MIN_POSTS = 8
ADDRESS_MIN_REVIEWER_REJECTIONS = 5
LOOKBACK_DAYS = 60

_SENDER = "lower(coalesce(metadata->'sender'->>'email',''))"
_REVIEWER_REJECT = (
    "status='rejected' AND coalesce(metadata->>'rejection_reason','') NOT IN ('exact_duplicate','duplicate_of_rejected')"
)


def _max_blocks() -> int:
    try:
        return min(max(int(os.getenv("HERMES_AUTO_BLOCK_MAX_PER_RUN", "10")), 0), 100)
    except ValueError:
        return 10


def find_domain_candidates() -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            f"""WITH g AS (
                    SELECT split_part({_SENDER}, '@', 2) AS value, count(*) AS posts
                    FROM drafts
                    WHERE draft_type='draft_job_requirement' AND created_at > now() - make_interval(days => %s)
                      AND {_SENDER} LIKE '%%@%%'
                    GROUP BY 1
                    HAVING count(*) >= %s
                       AND count(*) FILTER (WHERE status IN ('draft','published')) = 0)
                SELECT value, posts FROM g
                WHERE value NOT IN (
                    SELECT split_part({_SENDER}, '@', 2) FROM drafts WHERE status='published')""",
            (LOOKBACK_DAYS, DOMAIN_MIN_POSTS),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows if r["value"] and r["value"] not in SHARED_DOMAINS]


def find_address_candidates() -> list[dict[str, Any]]:
    shared = sorted(SHARED_DOMAINS)
    with cursor() as cur:
        cur.execute(
            f"""SELECT {_SENDER} AS value, count(*) AS posts,
                       count(*) FILTER (WHERE {_REVIEWER_REJECT}) AS rejected
                FROM drafts
                WHERE draft_type='draft_job_requirement' AND created_at > now() - make_interval(days => %s)
                  AND split_part({_SENDER}, '@', 2) = ANY(%s)
                GROUP BY 1
                HAVING count(*) >= %s
                   AND count(*) FILTER (WHERE status IN ('draft','published')) = 0
                   AND count(*) FILTER (WHERE {_REVIEWER_REJECT}) >= %s""",
            (LOOKBACK_DAYS, shared, ADDRESS_MIN_POSTS, ADDRESS_MIN_REVIEWER_REJECTIONS),
        )
        return [dict(r) for r in cur.fetchall()]


def _already_blocked(match_type: str, value: str) -> bool:
    with cursor() as cur:
        cur.execute("SELECT 1 FROM sender_blocklist WHERE match_type=%s AND value=%s", (match_type, value))
        return cur.fetchone() is not None


def run_auto_blocklist(max_blocks: int | None = None) -> dict[str, Any]:
    limit = _max_blocks() if max_blocks is None else max_blocks
    added: list[dict[str, Any]] = []
    for match_type, finder in (("domain", find_domain_candidates), ("email", find_address_candidates)):
        for candidate in finder():
            if len(added) >= limit:
                break
            value = candidate["value"]
            if _already_blocked(match_type, value):
                continue
            reason = f"auto: {candidate['posts']} posts in {LOOKBACK_DAYS}d, none usable"
            if candidate.get("rejected"):
                reason += f", {candidate['rejected']} rejected in review"
            add_block(match_type, value, reason=reason)
            added.append({"match_type": match_type, "value": value, "posts": candidate["posts"]})
    return {"blocked": len(added), "added": added}
