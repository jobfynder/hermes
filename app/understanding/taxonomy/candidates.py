"""Taxonomy candidate detection (HERMES-900): finds skill-shaped terms in
a real posting's own "Required Skills"/"Preferred Skills" section that
canonical_skills.json doesn't recognize, and queues them for human review
via the taxonomy_candidates table.

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
from app.understanding.taxonomy.loader import (
    add_canonical_skill,
    build_skill_alias_index,
    normalize_taxonomy_key,
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


def record_taxonomy_candidates(
    text: str,
    draft_id: str | None = None,
    sender_domain: str | None = None,
) -> list[str]:
    """Upserts each unrecognized skill-shaped term into taxonomy_candidates,
    bumping occurrence_count / distinct_senders / sample_draft_ids on a
    repeat sighting rather than creating a duplicate row. Returns the list
    of terms recorded (empty if the posting had no skills section, or
    every term it named was already known).
    """
    unknown_terms = find_unknown_skill_terms(text or "")

    if not unknown_terms:
        return []

    for term in unknown_terms:
        normalized_term = normalize_taxonomy_key(term)

        with cursor() as cur:
            cur.execute(
                "SELECT id, distinct_senders, sample_draft_ids FROM taxonomy_candidates "
                "WHERE signal_type = 'skill' AND normalized_term = %s",
                (normalized_term,),
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
                    "VALUES ('skill', %s, %s, 1, %s, %s)",
                    (
                        term,
                        normalized_term,
                        json.dumps([sender_domain] if sender_domain else []),
                        json.dumps([draft_id] if draft_id else []),
                    ),
                )

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
        return [dict(row) for row in cur.fetchall()]


def approve_taxonomy_candidate(
    candidate_id: int,
    category: str = "Tool/Technology",
    skill_type: str = "tool",
) -> dict:
    """Adds the candidate's term to canonical_skills.json (live immediately,
    no redeploy -- see add_canonical_skill) and marks the queue row
    approved. Only ever called from a human clicking "Approve" in the
    admin UI -- see the module docstring for why this never happens
    automatically.
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
        add_canonical_skill(name=row["term"], category=category, skill_type=skill_type)

    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status = 'approved', reviewed_at = now() WHERE id = %s",
            (candidate_id,),
        )

    return {"approved": True, "term": row["term"]}


def reject_taxonomy_candidate(candidate_id: int) -> dict:
    with cursor() as cur:
        cur.execute(
            "UPDATE taxonomy_candidates SET status = 'rejected', reviewed_at = now() "
            "WHERE id = %s AND status = 'pending' RETURNING term",
            (candidate_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"rejected": False, "reason": "candidate_not_found_or_already_reviewed"}

    return {"rejected": True, "term": row["term"]}
