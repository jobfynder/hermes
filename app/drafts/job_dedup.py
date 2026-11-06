"""Cross-vendor job de-duplication.

The same requirement reaches Hermes many times: from several vendors, and
re-sent by the same one. Measured on 14 days of production (33.8k live posts),
title + location alone collapses them to ~16.8k distinct roles (~50% fewer).
Pushing each copy to Jobfynder Core would flood it with duplicate jobs, so
posts are grouped into clusters and only one canonical post per cluster is
ever offered to the Core outbox.

Cluster key = normalised job title + city + state (location understood
through the same Core-vocabulary parsing used for the push). Two different
roles with the same title in the same city (different clients) would collide
on the key alone, so a post only joins an existing cluster when its required
skills overlap the canonical post's (Jaccard >= SKILL_OVERLAP); otherwise it
starts its own cluster. Posts with no usable title never cluster. Canonical =
the first post seen. Pure grouping: nothing is deleted or modified in drafts.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.integrations.core_vocabulary import split_location
from app.runtime.db import cursor

SKILL_OVERLAP = 0.5
_REC = "d.payload->'structured_data'->'email_parsing'->'records'->0"


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", (value or "").lower()).strip()


def cluster_key(record: dict[str, Any]) -> str | None:
    title = _norm(record.get("job_title"))
    if len(title) < 3:
        return None
    loc = split_location(record.get("location"))
    place = _norm(f"{loc.get('city', '')} {loc.get('state', '')}") or loc.get("work_mode", "").lower() or "unspecified"
    return hashlib.sha1(f"{title}|{place}".encode()).hexdigest()


def _skills(record: dict[str, Any]) -> set[str]:
    return {_norm(s) for s in (record.get("required_skills") or []) if isinstance(s, str) and _norm(s)}


def _similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0  # nothing to distinguish them by
    return len(a & b) / len(a | b)


def assign_cluster(cur, draft_id: str, record: dict[str, Any]) -> dict[str, Any] | None:
    key = cluster_key(record)
    if key is None:
        return None
    skills = _skills(record)
    cur.execute("SELECT cluster_id, canonical_draft_id, skills FROM job_clusters WHERE cluster_key=%s", (key,))
    best = None
    for row in cur.fetchall():
        score = _similarity(skills, set(row["skills"] or []))
        if score >= SKILL_OVERLAP and (best is None or score > best[1]):
            best = (row, score)
    if best:
        row, score = best
        cur.execute(
            "INSERT INTO job_cluster_members(draft_id, cluster_id, similarity) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (draft_id, row["cluster_id"], round(score, 3)),
        )
        cur.execute("UPDATE job_clusters SET member_count=member_count+1, updated_at=now() WHERE cluster_id=%s", (row["cluster_id"],))
        return {"cluster_id": row["cluster_id"], "canonical": False}
    cur.execute(
        "INSERT INTO job_clusters(cluster_key, canonical_draft_id, skills) VALUES (%s,%s,%s) RETURNING cluster_id",
        (key, draft_id, json.dumps(sorted(skills))),
    )
    cluster_id = cur.fetchone()["cluster_id"]
    cur.execute(
        "INSERT INTO job_cluster_members(draft_id, cluster_id, similarity) VALUES (%s,%s,1) ON CONFLICT DO NOTHING",
        (draft_id, cluster_id),
    )
    return {"cluster_id": cluster_id, "canonical": True}


def cluster_new_drafts(limit: int = 500, days: int = 14) -> dict[str, int]:
    """Cluster the oldest not-yet-clustered recent job requirements (oldest
    first, so the first post seen is canonical). One transaction per call."""
    stats = {"examined": 0, "new_clusters": 0, "joined": 0, "unclusterable": 0}
    with cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute(
            f"""SELECT d.draft_id, {_REC} AS rec FROM drafts d
                WHERE d.draft_type='draft_job_requirement' AND d.status IN ('draft','needs_review')
                  AND d.created_at > now() - make_interval(days => %s)
                  AND d.metadata->>'exact_content_duplicate_of' IS NULL
                  AND NOT EXISTS (SELECT 1 FROM job_cluster_members m WHERE m.draft_id = d.draft_id)
                  AND NOT EXISTS (SELECT 1 FROM job_unclusterable u WHERE u.draft_id = d.draft_id)
                ORDER BY d.created_at LIMIT %s""",
            (days, limit),
        )
        rows = cur.fetchall()
        for row in rows:
            stats["examined"] += 1
            result = assign_cluster(cur, str(row["draft_id"]), row["rec"] or {})
            if result is None:
                stats["unclusterable"] += 1
                cur.execute("INSERT INTO job_unclusterable(draft_id) VALUES (%s) ON CONFLICT DO NOTHING", (row["draft_id"],))
            elif result["canonical"]:
                stats["new_clusters"] += 1
            else:
                stats["joined"] += 1
    return stats


def get_cluster_stats() -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SELECT count(*) AS clusters, coalesce(sum(member_count),0)::int AS members FROM job_clusters")
        row = cur.fetchone()
        cur.execute("SELECT count(*) AS n FROM job_clusters WHERE member_count > 1")
        multi = cur.fetchone()["n"]
    return {"clusters": row["clusters"], "clustered_posts": row["members"], "clusters_with_duplicates": multi}
