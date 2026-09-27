from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.prompt_runtime.extraction_fallback import run_llm_fallback
from app.runtime.db import cursor
from app.skill_intelligence.models import SkillEnrichmentProposal
from app.skill_intelligence.service import get_skill, resolve
from app.understanding.taxonomy.candidates import queue_user_skill_candidate
from app.understanding.taxonomy.loader import (
    apply_canonical_skill_enrichment,
    get_canonical_skill_entries,
)


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
            "occurrence_count, status, first_seen_at, last_seen_at, reviewed_at, reviewed_by, "
            "proposal, proposal_status, proposal_prompt_id, proposal_run_id, proposal_model, "
            "proposal_generated_at, proposal_error, approved_values, apply_result "
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
            "proposal_generated_at": row["proposal_generated_at"].isoformat() if row["proposal_generated_at"] else None,
        }
        for row in rows
    ]


def _clean_proposal(raw: dict, requested_fields: list[str], skill_id: str | None = None) -> dict:
    proposal = SkillEnrichmentProposal.model_validate(raw).model_dump()
    requested = set(requested_fields)
    for field in ALLOWED_ENRICHMENT_FIELDS - requested:
        proposal[field] = None if field in {"definition", "recruiter_explanation"} else []
    for field in ("definition", "recruiter_explanation"):
        if proposal.get(field):
            proposal[field] = proposal[field].strip()
    aliases: list[str] = []
    seen_aliases: set[str] = set()
    for raw_alias in proposal["aliases"]:
        alias = raw_alias.strip()
        key = alias.casefold()
        if not alias or key in seen_aliases:
            continue
        resolved = resolve(alias, allow_fuzzy=False)
        if resolved["matched"]:
            if resolved["skill_id"] != skill_id:
                raise ValueError(f"Alias already belongs to {resolved['canonical_name']}: {alias}")
            continue
        seen_aliases.add(key)
        aliases.append(alias)
    proposal["aliases"] = aliases

    relationships: list[dict[str, str]] = []
    seen_relationships: set[tuple[str, str]] = set()
    for relationship in proposal["relationships"]:
        resolved = resolve(relationship["skill"], allow_fuzzy=False)
        if not resolved["matched"]:
            raise ValueError(f"Relationship target is not a canonical skill: {relationship['skill']}")
        if resolved["skill_id"] == skill_id:
            raise ValueError("A skill cannot be related to itself")
        identity = (relationship["type"], resolved["skill_id"])
        if identity not in seen_relationships:
            seen_relationships.add(identity)
            relationships.append({"type": relationship["type"], "skill": resolved["canonical_name"]})
    proposal["relationships"] = relationships
    proposal["related_roles"] = list(
        dict.fromkeys(role.strip() for role in proposal["related_roles"] if role.strip())
    )
    return proposal


def _field_present(card: dict, proposal: dict, field: str) -> bool:
    current = card.get(field)
    return bool(current) or bool(proposal.get(field))


def save_enrichment_proposal(request_id: int, proposal: dict) -> dict:
    """Store a validated review draft. This never mutates the taxonomy."""
    with cursor() as cur:
        cur.execute(
            "SELECT skill_id, requested_fields FROM taxonomy_enrichment_requests "
            "WHERE id=%s AND status='pending' FOR UPDATE",
            (request_id,),
        )
        pending = cur.fetchone()
        if not pending:
            raise LookupError("Pending enrichment request not found")
        cleaned = _clean_proposal(
            proposal, list(pending["requested_fields"] or []), pending["skill_id"]
        )
        cur.execute(
            "UPDATE taxonomy_enrichment_requests SET proposal=%s, proposal_status='ready', "
            "proposal_error=NULL WHERE id=%s RETURNING id, skill_id, canonical_name, "
            "requested_fields, proposal, proposal_status",
            (json.dumps(cleaned), request_id),
        )
        row = cur.fetchone()
    return dict(row)


def generate_enrichment_proposal(request_id: int) -> dict:
    """Use Hermes prompt runtime to draft fields for later human approval."""
    with cursor() as cur:
        cur.execute(
            "SELECT id, skill_id, canonical_name, requested_fields, notes, proposal, proposal_status, "
            "proposal_prompt_id, proposal_run_id, proposal_model, proposal_generated_at, proposal_error "
            "FROM taxonomy_enrichment_requests WHERE id=%s AND status='pending' FOR UPDATE",
            (request_id,),
        )
        pending = cur.fetchone()
        if not pending:
            raise LookupError("Pending enrichment request not found")
        if pending["proposal_status"] == "ready":
            result = dict(pending)
            if result.get("proposal_generated_at"):
                result["proposal_generated_at"] = result["proposal_generated_at"].isoformat()
            return result
        generated_at = pending.get("proposal_generated_at")
        if (
            pending["proposal_status"] == "generating"
            and generated_at
            and generated_at > datetime.now(UTC) - timedelta(minutes=10)
        ):
            result = dict(pending)
            result["proposal_generated_at"] = generated_at.isoformat()
            return result
        cur.execute(
            "UPDATE taxonomy_enrichment_requests SET proposal_status='generating', "
            "proposal_generated_at=now(), proposal_error=NULL WHERE id=%s",
            (request_id,),
        )
    card = get_skill(pending["skill_id"])
    if card is None:
        raise LookupError("Canonical skill not found")

    requested = list(pending["requested_fields"] or [])
    known = get_canonical_skill_entries()
    same_category = [str(row.get("name")) for row in known if row.get("category") == card.get("category")]
    other_names = [str(row.get("name")) for row in known if row.get("category") != card.get("category")]
    known_names = list(dict.fromkeys([*same_category, *other_names]))[:800]
    outcome = run_llm_fallback(
        prompt_id="jf.taxonomy.skill-enrichment.propose",
        variables={
            "canonical_name": card["canonical_name"],
            "requested_fields_json": json.dumps(requested),
            "current_skill_json": json.dumps(card, ensure_ascii=False),
            "known_skill_names_json": json.dumps(known_names, ensure_ascii=False),
            "reviewer_notes": pending.get("notes") or "",
        },
        source="taxonomy_enrichment_review",
        cache_ttl_seconds=86_400,
    )
    proposal = None
    error = None
    if outcome.get("used"):
        try:
            proposal = _clean_proposal(
                outcome.get("extracted") or {}, requested, pending["skill_id"]
            )
        except Exception as exc:  # Pydantic provides the field-level reason to the reviewer.
            error = f"invalid_llm_proposal:{exc}"
    else:
        error = str(outcome.get("reason") or "llm_proposal_unavailable")

    status = "ready" if proposal is not None else "failed"
    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_enrichment_requests SET proposal=%s, proposal_status=%s, "
            "proposal_prompt_id=%s, proposal_run_id=%s, proposal_model=%s, "
            "proposal_generated_at=now(), proposal_error=%s WHERE id=%s "
            "RETURNING id, skill_id, canonical_name, requested_fields, proposal, proposal_status, "
            "proposal_prompt_id, proposal_run_id, proposal_model, proposal_generated_at, proposal_error",
            (
                json.dumps(proposal) if proposal is not None else None,
                status,
                outcome.get("prompt_id"),
                outcome.get("run_id"),
                outcome.get("model_used"),
                error,
                request_id,
            ),
        )
        row = cur.fetchone()
    result = dict(row)
    result["proposal_generated_at"] = result["proposal_generated_at"].isoformat()
    return result


def review_enrichment_request(
    request_id: int,
    decision: str,
    reviewed_by: str | None,
    proposal_override: dict | None = None,
) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected")
    with cursor() as cur:
        cur.execute(
            "SELECT skill_id, requested_fields, proposal FROM taxonomy_enrichment_requests "
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
            proposal = _clean_proposal(
                proposal_override or pending.get("proposal") or {},
                list(pending["requested_fields"] or []),
                pending["skill_id"],
            )
            missing = [field for field in pending["requested_fields"] if not _field_present(card, proposal, field)]
            if missing:
                raise ValueError(
                    "Generate or complete the requested proposal fields before approval: " + ", ".join(missing)
                )
            apply_result = apply_canonical_skill_enrichment(pending["skill_id"], proposal, reviewed_by)
            if apply_result.get("reason") == "skill_not_found":
                raise LookupError("Canonical skill not found")
        else:
            proposal = pending.get("proposal")
            apply_result = None
        cur.execute(
            "UPDATE taxonomy_enrichment_requests SET status=%s, reviewed_at=now(), reviewed_by=%s, "
            "approved_values=%s, apply_result=%s "
            "WHERE id=%s AND status='pending' RETURNING id, skill_id, canonical_name, status",
            (
                decision,
                reviewed_by,
                json.dumps(proposal) if decision == "approved" else None,
                json.dumps(apply_result) if apply_result is not None else None,
                request_id,
            ),
        )
        row = cur.fetchone()
    return {**dict(row), "apply_result": apply_result}


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
    fields = [field for field in fields if not card.get(field)]
    if not fields:
        return {
            "result_version": "hermes_skill_suggestion_v1",
            "suggestion_type": suggestion_type,
            "outcome": "already_reviewed",
            "candidate_id": None,
            "status": "approved",
            "occurrence_count": None,
        }

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
            previous_fields = sorted(existing["requested_fields"] or [])
            merged_fields = sorted(
                field
                for field in (set(previous_fields) | set(fields))
                if not card.get(field)
            )
            proposal_invalidated = merged_fields != previous_fields
            refs = list(existing["request_refs"] or [])
            increment = 1
            if clean_ref:
                cur.execute(
                    "INSERT INTO taxonomy_enrichment_request_evidence "
                    "(request_id, request_ref, source_domain) VALUES (%s,%s,%s) "
                    "ON CONFLICT (request_id, request_ref) DO NOTHING RETURNING request_ref",
                    (existing["id"], clean_ref, clean_domain),
                )
                increment = 1 if cur.fetchone() else 0
            if clean_ref and clean_ref not in refs and len(refs) < 20:
                refs.append(clean_ref)
            cur.execute(
                "UPDATE taxonomy_enrichment_requests SET requested_fields=%s, "
                "notes=coalesce(%s, notes), source_domain=coalesce(%s, source_domain), "
                "request_refs=%s, occurrence_count=occurrence_count+%s, last_seen_at=now(), "
                "proposal=CASE WHEN %s THEN NULL ELSE proposal END, "
                "proposal_status=CASE WHEN %s THEN 'not_generated' ELSE proposal_status END, "
                "proposal_error=CASE WHEN %s THEN NULL ELSE proposal_error END, "
                "proposal_prompt_id=CASE WHEN %s THEN NULL ELSE proposal_prompt_id END, "
                "proposal_run_id=CASE WHEN %s THEN NULL ELSE proposal_run_id END, "
                "proposal_model=CASE WHEN %s THEN NULL ELSE proposal_model END, "
                "proposal_generated_at=CASE WHEN %s THEN NULL ELSE proposal_generated_at END "
                "WHERE id=%s RETURNING id, occurrence_count, status",
                (
                    json.dumps(merged_fields), clean_notes, clean_domain, json.dumps(refs), increment,
                    proposal_invalidated, proposal_invalidated, proposal_invalidated,
                    proposal_invalidated, proposal_invalidated, proposal_invalidated,
                    proposal_invalidated, existing["id"],
                ),
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
            if clean_ref:
                cur.execute(
                    "INSERT INTO taxonomy_enrichment_request_evidence "
                    "(request_id, request_ref, source_domain) VALUES (%s,%s,%s) "
                    "ON CONFLICT (request_id, request_ref) DO NOTHING",
                    (row["id"], clean_ref, clean_domain),
                )
    return {
        "result_version": "hermes_skill_suggestion_v1",
        "suggestion_type": suggestion_type,
        "outcome": "queued",
        "candidate_id": row["id"],
        "status": row["status"],
        "occurrence_count": row["occurrence_count"],
    }
