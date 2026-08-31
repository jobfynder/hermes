"""Taxonomy candidate detection (HERMES-900): finds skill-shaped terms in
a real posting's own "Required Skills"/"Preferred Skills" section, and
job titles the parser extracted, that the taxonomy doesn't recognize --
queues both for human review via the taxonomy_candidates table.

Deliberately never adds anything to the taxonomy itself -- an unreviewed
addition can silently corrupt matching for every future email (a company
name or a typo that happens to repeat would look identical to a real new
tool name to any purely frequency-based rule). occurrence_count and
distinct_senders exist so a reviewer can tell "this showed up once, from
one recruiter, probably a typo" from "this showed up 40 times across 12
different domains, it's SAP Fiori and we're missing it" at a glance --
the judgment call itself still belongs to a human, made through the
taxonomy-candidates admin endpoints (app/routers/taxonomy_admin.py).
"""

from __future__ import annotations

import json
import re

from app.runtime.db import cursor
from app.understanding.parsers.job_description_fields import (
    extract_preferred_skills_text,
    extract_required_skills_text,
)
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import (
    add_canonical_job_title,
    add_canonical_skill,
    build_skill_alias_index,
    build_title_alias_index,
    normalize_taxonomy_key,
    set_skill_description,
)

# Common non-skill filler that shows up inside skills lists but is not
# itself a skill -- "Java, Spring, and more", "SQL, etc.", "AWS (required)".
_FILLER_TERMS = {
    "and", "or", "etc", "etc.", "and more", "and others", "required",
    "preferred", "plus", "a plus", "nice to have", "must have",
    "years of experience", "experience", "strong", "excellent",
    "good to have", "knowledge of", "hands on", "hands-on",
}

_SPLIT_RE = re.compile(r"[,\n|/••]+")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _candidate_terms(section_text: str | None) -> list[str]:
    if not section_text:
        return []

    terms: list[str] = []

    for raw_item in _SPLIT_RE.split(section_text):
        item = _PARENTHETICAL_RE.sub("", raw_item).strip(" -.:;\t")

        if not item:
            continue

        lowered = item.lower()

        if lowered in _FILLER_TERMS:
            continue

        # A real skill token is short -- "Amazon Connect", "TIBCO
        # BusinessWorks", "SAP Fiori" -- not a sentence. Anything this long
        # is almost always prose that leaked past the comma/newline split
        # (e.g. "5+ years building distributed systems"), not a term.
        if len(item) < 2 or len(item) > 40:
            continue

        # Needs at least one letter (skip bare years/numbers like "5+").
        if not re.search(r"[A-Za-z]", item):
            continue

        terms.append(item)

    return terms


def find_unknown_skill_terms(text: str) -> list[str]:
    alias_index = build_skill_alias_index()
    seen_normalized: set[str] = set()
    unknown: list[str] = []

    for section in (
        extract_required_skills_text(text),
        extract_preferred_skills_text(text),
    ):
        for term in _candidate_terms(section):
            key = normalize_taxonomy_key(term)

            if not key or key in seen_normalized:
                continue

            seen_normalized.add(key)

            if key in alias_index:
                continue

            unknown.append(term)

    return unknown


# A job title candidate can legitimately be longer than a skill token
# ("Senior SAP ERP Integration Consultant" is a real title), but this
# still guards against a parser mistake handing through a whole sentence
# instead of a title.
_MAX_JOB_TITLE_CANDIDATE_LENGTH = 80


def find_unknown_job_title(job_title: str | None) -> str | None:
    if not job_title:
        return None

    cleaned = job_title.strip()

    if not cleaned or len(cleaned) > _MAX_JOB_TITLE_CANDIDATE_LENGTH:
        return None

    key = normalize_taxonomy_key(cleaned)

    if not key or key in build_title_alias_index():
        return None

    return cleaned


def _upsert_candidate(
    signal_type: str,
    term: str,
    draft_id: str | None,
    sender_domain: str | None,
) -> None:
    """Shared upsert for both signal types -- bumps occurrence_count /
    distinct_senders / sample_draft_ids on a repeat sighting rather than
    creating a duplicate row.
    """
    normalized_term = normalize_taxonomy_key(term)

    with cursor() as cur:
        cur.execute(
            "SELECT id, distinct_senders, sample_draft_ids FROM taxonomy_candidates "
            "WHERE signal_type = %s AND normalized_term = %s",
            (signal_type, normalized_term),
        )
        existing = cur.fetchone()

        if existing:
            senders = set(existing["distinct_senders"] or [])
            if sender_domain:
                senders.add(sender_domain)

            sample_ids = list(existing["sample_draft_ids"] or [])
            if draft_id and draft_id not in sample_ids and len(sample_ids) < 10:
                sample_ids.append(draft_id)

            cur.execute(
                "UPDATE taxonomy_candidates SET occurrence_count = occurrence_count + 1, "
                "distinct_senders = %s, sample_draft_ids = %s, last_seen_at = now() "
                "WHERE id = %s",
                (json.dumps(sorted(senders)), json.dumps(sample_ids), existing["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO taxonomy_candidates "
                "(signal_type, term, normalized_term, occurrence_count, distinct_senders, sample_draft_ids) "
                "VALUES (%s, %s, %s, 1, %s, %s)",
                (
                    signal_type,
                    term,
                    normalized_term,
                    json.dumps([sender_domain] if sender_domain else []),
                    json.dumps([draft_id] if draft_id else []),
                ),
            )


def record_taxonomy_candidates(
    text: str,
    draft_id: str | None = None,
    sender_domain: str | None = None,
    job_titles: list[str] | None = None,
) -> list[str]:
    """Upserts each unrecognized skill-shaped term (from the posting's own
    Required/Preferred Skills sections) and each unrecognized job title
    (already extracted by the deterministic parser -- passed in rather
    than re-derived here) into taxonomy_candidates. Returns the skill
    terms recorded, same as before this function also handled titles.
    """
    unknown_terms = find_unknown_skill_terms(text or "")

    for term in unknown_terms:
        _upsert_candidate("skill", term, draft_id, sender_domain)

    seen_titles: set[str] = set()
    for job_title in job_titles or []:
        unknown_title = find_unknown_job_title(job_title)
        if not unknown_title:
            continue
        key = normalize_taxonomy_key(unknown_title)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        _upsert_candidate("job_title", unknown_title, draft_id, sender_domain)

    return unknown_terms


def list_taxonomy_candidates(status: str = "pending") -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT id, signal_type, term, normalized_term, occurrence_count, "
            "distinct_senders, sample_draft_ids, status, first_seen_at, last_seen_at "
            "FROM taxonomy_candidates WHERE status = %s "
            "ORDER BY occurrence_count DESC, last_seen_at DESC",
            (status,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    # psycopg returns real datetime objects for TIMESTAMPTZ columns, but
    # the response model (TaxonomyCandidateEntry in app/routers/
    # moderation.py) declares first_seen_at/last_seen_at as str -- FastAPI
    # response validation rejects a raw datetime there instead of
    # stringifying it, which surfaced as a 500 on GET /taxonomy-candidates
    # the moment a real row existed (empty results never hit this path).
    for row in rows:
        if row.get("first_seen_at"):
            row["first_seen_at"] = row["first_seen_at"].isoformat()
        if row.get("last_seen_at"):
            row["last_seen_at"] = row["last_seen_at"].isoformat()

    return rows


def edit_taxonomy_candidate(candidate_id: int, term: str) -> dict:
    """Corrects a pending candidate's term before approval -- e.g. a parser
    artifact like a stray "AWS (required)" or a truncated title. Only ever
    touches `pending` rows; a candidate already approved/rejected is final.
    Does not itself approve anything, so the reviewer still makes that call
    afterward with the corrected term.
    """
    cleaned = (term or "").strip()
    if not cleaned:
        return {"edited": False, "reason": "term_cannot_be_empty"}
    if len(cleaned) > 120:
        return {"edited": False, "reason": "term_too_long"}

    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET term = %s, normalized_term = %s "
            "WHERE id = %s AND status = 'pending' RETURNING term",
            (cleaned, normalize_taxonomy_key(cleaned), candidate_id),
        )
        row = cur.fetchone()

    if not row:
        return {"edited": False, "reason": "candidate_not_found_or_already_reviewed"}

    return {"edited": True, "term": row["term"]}


def approve_taxonomy_candidate(
    candidate_id: int,
    category: str = "Tool/Technology",
    skill_type: str = "tool",
    family: str = "Unclassified",
    seniority: str = "unspecified",
    reviewed_by: str | None = None,
) -> dict:
    """Adds the candidate's term to canonical_skills.json or job_titles.json
    (live immediately, no redeploy -- see add_canonical_skill/
    add_canonical_job_title) and marks the queue row approved. Only ever
    called from a human clicking "Approve" in the admin UI -- see the
    module docstring for why this never happens automatically.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT term, signal_type FROM taxonomy_candidates WHERE id = %s AND status = 'pending'",
            (candidate_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"approved": False, "reason": "candidate_not_found_or_already_reviewed"}

    if row["signal_type"] == "skill":
        # Best-effort: a description is a nice-to-have annotation the
        # approval itself never depends on. generate_skill_description
        # already swallows its own failures and returns None rather than
        # raising, but wrapped again here so a future change to it can't
        # turn a missing description into a failed approval.
        try:
            description = generate_skill_description(row["term"], category=category)
        except Exception:  # noqa: BLE001
            description = None

        add_canonical_skill(
            name=row["term"], category=category, skill_type=skill_type, description=description
        )
    elif row["signal_type"] == "job_title":
        add_canonical_job_title(title=row["term"], family=family, seniority=seniority)

    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status = 'approved', reviewed_at = now(), reviewed_by = %s WHERE id = %s",
            (reviewed_by, candidate_id),
        )

    return {"approved": True, "term": row["term"]}


def reject_taxonomy_candidate(candidate_id: int, reviewed_by: str | None = None) -> dict:
    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status = 'rejected', reviewed_at = now(), reviewed_by = %s "
            "WHERE id = %s AND status = 'pending' RETURNING term",
            (reviewed_by, candidate_id),
        )
        row = cur.fetchone()

    if not row:
        return {"rejected": False, "reason": "candidate_not_found_or_already_reviewed"}

    return {"rejected": True, "term": row["term"]}


def bulk_approve_taxonomy_candidates(candidate_ids: list[int], reviewed_by: str | None = None) -> dict:
    """Approves a batch of pending candidates in one call -- the review
    page's "Approve selected" action. Each candidate keeps its own
    signal_type (skill vs job_title), so approve_taxonomy_candidate's
    normal per-type handling (description generation for skills, etc.)
    still runs individually per id; this is just a loop over it with a
    default category/skill_type/family/seniority, the same defaults the
    page's single "Approve" button already uses. One candidate failing
    (already reviewed by someone else in the meantime, say) never stops
    the rest of the batch.
    """
    approved: list[str] = []
    failed: list[dict] = []

    for candidate_id in candidate_ids:
        result = approve_taxonomy_candidate(candidate_id, reviewed_by=reviewed_by)
        if result.get("approved"):
            approved.append(result["term"])
        else:
            failed.append({"candidate_id": candidate_id, "reason": result.get("reason")})

    return {"approved_count": len(approved), "approved_terms": approved, "failed": failed}


def bulk_reject_taxonomy_candidates(candidate_ids: list[int], reviewed_by: str | None = None) -> dict:
    rejected: list[str] = []
    failed: list[dict] = []

    for candidate_id in candidate_ids:
        result = reject_taxonomy_candidate(candidate_id, reviewed_by=reviewed_by)
        if result.get("rejected"):
            rejected.append(result["term"])
        else:
            failed.append({"candidate_id": candidate_id, "reason": result.get("reason")})

    return {"rejected_count": len(rejected), "rejected_terms": rejected, "failed": failed}


def record_skill_usage(skill_names: list[str]) -> None:
    """Upserts times_seen/last_seen_at for each canonical skill name a
    parse actually matched -- called once per draft (app/channels/
    service.py) with that draft's required+preferred (or primary) skills.
    Best-effort by design at the call site: a failure here must never
    block draft creation.
    """
    if not skill_names:
        return

    with cursor() as cur:
        cur.executemany(
            "INSERT INTO skill_usage_stats (skill_name, times_seen, last_seen_at, updated_at) "
            "VALUES (%s, 1, now(), now()) "
            "ON CONFLICT (skill_name) DO UPDATE SET "
            "times_seen = skill_usage_stats.times_seen + 1, last_seen_at = now(), updated_at = now()",
            [(name,) for name in dict.fromkeys(skill_names)],
        )


def get_skill_usage_stats() -> dict[str, dict]:
    with cursor() as cur:
        cur.execute("SELECT skill_name, times_seen, last_seen_at FROM skill_usage_stats")
        rows = cur.fetchall()

    return {
        row["skill_name"]: {
            "times_seen": row["times_seen"],
            "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
        }
        for row in rows
    }


def update_skill_description(name: str, description: str, edited_by: str | None = None) -> dict:
    """The one and only write path for the Skills taxonomy page's inline
    edit -- always source="human_edited", so this can never be blocked
    by set_skill_description's own protection against an automated
    regeneration clobbering a prior human edit (that guard only fires
    against source="ai_generated" callers). Clearing a description is
    just editing it to an empty string; there is no separate delete.
    """
    ok = set_skill_description(name, description, source="human_edited", edited_by=edited_by)

    if not ok:
        return {"updated": False, "reason": "skill_not_found"}

    return {"updated": True, "name": name}
