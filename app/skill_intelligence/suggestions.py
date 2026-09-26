from __future__ import annotations

import json

from app.runtime.db import cursor
from app.skill_intelligence.service import get_skill
from app.understanding.taxonomy.candidates import queue_user_skill_candidate


ALLOWED_ENRICHMENT_FIELDS = {
    "definition",
    "recruiter_explanation",
    "aliases",
    "relationships",
    "related_roles",
}


def list_enrichment_requests(status: str = "pending") -> list[dict]:
    if status not in {"pending", "approved", "rejected"}:
        raise ValueError("Unsupported enrichment request status")
    with cursor() as cur:
        cur.execute(
            "SELECT id, skill_id, canonical_name, requested_fields, notes, source_domain, "
            "occurrence_count, status, first_seen_at, last_seen_at, reviewed_at, reviewed_by "
            "FROM taxonomy_enrichment_requests WHERE status=%s ORDER BY last_seen_at DESC LIMIT 500",
            (status,),
        )
        rows = cur.fetchall()
    return [
        {
            **dict(row),
            "first_seen_at": row["first_seen_at"].isoformat(),
            "last_seen_at": row["last_seen_at"].isoformat(),
            "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        }
        for row in rows
    ]


def review_enrichment_request(request_id: int, decision: str, reviewed_by: str | None) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected")
    with cursor() as cur:
        cur.execute(
            "SELECT skill_id, requested_fields FROM taxonomy_enrichment_requests "
            "WHERE id=%s AND status='pending' FOR UPDATE",
            (request_id,),
        )
        pending = cur.fetchone()
        if not pending:
            raise LookupError("Pending enrichment request not found")
        if decision == "approved":
            card = get_skill(pending["skill_id"])
            if card is None:
                raise LookupError("Canonical skill not found")
            missing = [field for field in pending["requested_fields"] if not card.get(field)]
            if missing:
                raise ValueError(
                    "Complete the requested taxonomy fields before approval: " + ", ".join(missing)
                )
        cur.execute(
            "UPDATE taxonomy_enrichment_requests SET status=%s, reviewed_at=now(), reviewed_by=%s "
            "WHERE id=%s AND status='pending' RETURNING id, skill_id, canonical_name, status",
            (decision, reviewed_by, request_id),
        )
        row = cur.fetchone()
    return dict(row)


def submit_skill_suggestion(
    *,
    suggestion_type: str,
    term: str | None,
    skill_id: str | None,
    requested_fields: list[str],
    notes: str | None,
    source_domain: str | None,
    request_ref: str | None,
) -> dict:
    if suggestion_type == "new_skill":
        result = queue_user_skill_candidate(
            term or "", request_ref=request_ref, source_domain=source_domain
        )
        return {
            "result_version": "hermes_skill_suggestion_v1",
            "suggestion_type": suggestion_type,
            **result,
        }

    if suggestion_type != "enrichment":
        raise ValueError("Unsupported suggestion type")
    if not skill_id:
        raise ValueError("skill_id is required for enrichment")
    card = get_skill(skill_id)
    if card is None:
        raise LookupError("Skill not found")
    fields = sorted(set(requested_fields) & ALLOWED_ENRICHMENT_FIELDS)
    if not fields:
        raise ValueError("Choose at least one supported field to enrich")

    clean_notes = " ".join((notes or "").replace("\x00", " ").split())[:500] or None
    clean_domain = (source_domain or "").strip().lower()[:253] or None
    clean_ref = (request_ref or "").strip()[:128] or None
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("taxonomy-enrichment:" + skill_id,))
        cur.execute(
            "SELECT id, requested_fields, request_refs FROM taxonomy_enrichment_requests "
            "WHERE skill_id = %s AND status = 'pending' FOR UPDATE",
            (skill_id,),
        )
        existing = cur.fetchone()
        if existing:
            merged_fields = sorted(set(existing["requested_fields"] or []) | set(fields))
            refs = list(existing["request_refs"] or [])
            increment = 0 if clean_ref and clean_ref in refs else 1
            if clean_ref and clean_ref not in refs and len(refs) < 20:
                refs.append(clean_ref)
            cur.execute(
                "UPDATE taxonomy_enrichment_requests SET requested_fields=%s, "
                "notes=coalesce(%s, notes), source_domain=coalesce(%s, source_domain), "
                "request_refs=%s, occurrence_count=occurrence_count+%s, last_seen_at=now() "
                "WHERE id=%s RETURNING id, occurrence_count, status",
                (json.dumps(merged_fields), clean_notes, clean_domain, json.dumps(refs), increment, existing["id"]),
            )
            row = cur.fetchone()
        else:
            cur.execute(
                "INSERT INTO taxonomy_enrichment_requests "
                "(skill_id, canonical_name, requested_fields, notes, source_domain, request_refs) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, occurrence_count, status",
                (
                    skill_id,
                    card["canonical_name"],
                    json.dumps(fields),
                    clean_notes,
                    clean_domain,
                    json.dumps([clean_ref] if clean_ref else []),
                ),
            )
            row = cur.fetchone()
    return {
        "result_version": "hermes_skill_suggestion_v1",
        "suggestion_type": suggestion_type,
        "outcome": "queued",
        "candidate_id": row["id"],
        "status": row["status"],
        "occurrence_count": row["occurrence_count"],
    }
