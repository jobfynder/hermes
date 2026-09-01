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
from functools import lru_cache

from app.runtime.db import cursor
from app.understanding.parsers.job_description_fields import (
    extract_preferred_skills_text,
    extract_required_skills_text,
)
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import (
    add_canonical_job_title,
    add_canonical_skill,
    bulk_apply_job_title_families,
    build_skill_alias_index,
    build_title_alias_index,
    get_job_title_entries,
    normalize_taxonomy_key,
    set_skill_description,
)
from app.understanding.taxonomy.title_family_classifier import classify_job_title_family

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

# Real production data: the exact same role shows up as several separate
# candidates purely because the vendor baked a location/work-mode tag
# onto the end of the title line -- "AEM Solutions Engineer Lead- NY
# Onsite", "AEM Solutions Lead IN Brooklyn". Stripping just these two
# specific, low-risk trailing shapes before dedup collapses that back
# into one candidate instead of five, without touching a genuinely
# distinguishing trailing parenthetical like "(Microsoft AI &
# Automation)" that isn't one of these three work-mode words.
_TITLE_NOISE_SUFFIX_RE = re.compile(
    r"(?i)\s*[-–—]\s*[A-Za-z .]{0,40}?\b(?:onsite|remote|hybrid)\b\.?\s*$"
    r"|\s+in\s+[A-Z][a-zA-Z]+\s*$"
    r"|\s*\((?:remote|onsite|hybrid)\)\s*$"
)


def _normalize_job_title_for_candidate(title: str) -> str:
    stripped = _TITLE_NOISE_SUFFIX_RE.sub("", title).strip()
    return stripped or title


def find_unknown_job_title(job_title: str | None) -> str | None:
    if not job_title:
        return None

    cleaned = _normalize_job_title_for_candidate(job_title.strip())

    if not cleaned or len(cleaned) > _MAX_JOB_TITLE_CANDIDATE_LENGTH:
        return None

    # Defense in depth against an extraction bug feeding a non-title
    # value in here (a real production incident: "Position: 1" being
    # read as job_title "1", queued 25+ times -- see the job_title
    # fallback chain in app/email_parsing/parsers.py, which now guards
    # against this at the source too). A real title always has a letter.
    if not re.search(r"[A-Za-z]", cleaned):
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


# Real production incident: with a 15-char floor and a 3-domain bar,
# this flooded the queue with 13,000+ candidates in under a day --
# "Job Description:", "Key Responsibilities", "Thanks & Regards," are
# NOT relay-specific boilerplate, they're standard section headers and
# signoffs every staffing company independently writes the same way.
# The "byte-identical across unrelated companies is a strong signal"
# assumption only holds for longer, more idiosyncratic text (a full
# sentence, a URL) -- short headers/labels/signoffs recur everywhere
# regardless of any shared template, precisely because they're generic
# English convention, not because of it. Raising the length floor to 40
# eliminates that entire class outright; raising the domain bar to 8
# adds a second margin without meaningfully slowing detection of a real
# relay pattern -- a genuine template line still crosses 8 domains
# within hours at this mailbox's real daily volume.
_MIN_BOILERPLATE_DISTINCT_SENDERS = 8
_MIN_BOILERPLATE_LINE_LENGTH = 40
_MAX_BOILERPLATE_LINE_LENGTH = 200


def _normalize_boilerplate_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def record_boilerplate_line_candidates(
    job_description: str | None, draft_id: str | None, sender_domain: str | None
) -> None:
    """Tracks every line in a *finished* job_description (after all
    existing deterministic cleaning -- app/email_parsing/parsers.py --
    already ran) that recurs verbatim across postings, the same
    detect-then-human-approves shape as an unrecognized skill or job
    title, so a vendor/relay footer pattern the cleaner doesn't already
    catch gets surfaced instead of silently reaching Core forever. Every
    distinct line seen gets a row (cheap -- just text), but
    list_taxonomy_candidates only ever shows one once it has crossed
    _MIN_BOILERPLATE_DISTINCT_SENDERS, so a real posting's own
    (single-company) content never floods the review queue.
    """
    if not job_description:
        return

    seen_in_this_description: set[str] = set()

    for raw_line in job_description.splitlines():
        line = raw_line.strip()
        if not (_MIN_BOILERPLATE_LINE_LENGTH <= len(line) <= _MAX_BOILERPLATE_LINE_LENGTH):
            continue

        normalized = _normalize_boilerplate_line(line)
        if not normalized or normalized in seen_in_this_description:
            continue
        seen_in_this_description.add(normalized)

        _upsert_candidate("boilerplate_line", line, draft_id, sender_domain)


def approve_boilerplate_line_candidate(candidate_id: int, reviewed_by: str | None = None) -> dict:
    with cursor() as cur:
        cur.execute(
            "SELECT term FROM taxonomy_candidates WHERE id = %s AND status = 'pending' "
            "AND signal_type = 'boilerplate_line'",
            (candidate_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"approved": False, "reason": "candidate_not_found_or_already_reviewed"}

    with cursor() as cur:
        cur.execute(
            "INSERT INTO approved_boilerplate_lines (normalized_line, sample_text, approved_by) "
            "VALUES (%s, %s, %s) ON CONFLICT (normalized_line) DO NOTHING",
            (_normalize_boilerplate_line(row["term"]), row["term"], reviewed_by),
        )
        cur.execute(
            "UPDATE taxonomy_candidates SET status = 'approved', reviewed_at = now(), reviewed_by = %s "
            "WHERE id = %s",
            (reviewed_by, candidate_id),
        )

    get_approved_boilerplate_lines.cache_clear()

    return {"approved": True, "term": row["term"]}


@lru_cache(maxsize=1)
def get_approved_boilerplate_lines() -> frozenset[str]:
    """Cached for the same reason canonical taxonomy reads are (this runs
    on every single job-requirement email parsed) -- cleared the instant
    a new pattern is approved (approve_boilerplate_line_candidate above),
    same live-immediately contract as approving a skill or job title.
    """
    with cursor() as cur:
        cur.execute("SELECT normalized_line FROM approved_boilerplate_lines")
        return frozenset(row["normalized_line"] for row in cur.fetchall())


def list_taxonomy_candidates(status: str = "pending") -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT id, signal_type, term, normalized_term, occurrence_count, "
            "distinct_senders, sample_draft_ids, status, first_seen_at, last_seen_at "
            "FROM taxonomy_candidates "
            "WHERE status = %s "
            # A boilerplate_line row only becomes visible once it's been
            # seen from enough distinct sender domains to be a real
            # pattern, not one company's own content -- see
            # record_boilerplate_line_candidates. skill/job_title rows
            # are unaffected, exactly as before.
            "AND (signal_type != 'boilerplate_line' OR jsonb_array_length(distinct_senders) >= %s) "
            "ORDER BY occurrence_count DESC, last_seen_at DESC",
            (status, _MIN_BOILERPLATE_DISTINCT_SENDERS),
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
    family: str | None = None,
    seniority: str = "unspecified",
    reviewed_by: str | None = None,
) -> dict:
    """Adds the candidate's term to canonical_skills.json or job_titles.json
    (live immediately, no redeploy -- see add_canonical_skill/
    add_canonical_job_title) and marks the queue row approved. Only ever
    called from a human clicking "Approve" in the admin UI -- see the
    module docstring for why this never happens automatically.

    family=None (the default -- distinct from "Unclassified", which a
    caller can still pass explicitly to force it) means "figure it out":
    a job_title candidate gets classified via classify_job_title_family
    (deterministic keyword rules first, LLM only as a fallback) instead
    of defaulting straight to "Unclassified". Approving used to leave
    every single title unclassified, every time, no matter how obvious
    ("Java Developer" -> Unclassified) -- a backlog that only a human
    manually clearing it, one row at a time, could ever shrink.

    signal_type='boilerplate_line' is handled separately by
    approve_boilerplate_line_candidate -- approving one adds it to
    approved_boilerplate_lines, not to either taxonomy file.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT signal_type FROM taxonomy_candidates WHERE id = %s AND status = 'pending'",
            (candidate_id,),
        )
        signal_type_row = cur.fetchone()

    if signal_type_row and signal_type_row["signal_type"] == "boilerplate_line":
        return approve_boilerplate_line_candidate(candidate_id, reviewed_by=reviewed_by)

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
        resolved_family = family
        if resolved_family is None:
            known_families = sorted(
                {(e.get("family") or "Unclassified") for e in get_job_title_entries()} - {"Unclassified"}
            )
            try:
                resolved_family, _method = classify_job_title_family(row["term"], known_families)
            except Exception:  # noqa: BLE001
                resolved_family = "Unclassified"

        add_canonical_job_title(title=row["term"], family=resolved_family, seniority=seniority)

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


def suggest_job_title_family(title: str) -> dict:
    """One-title preview for the Job titles page's per-row "Suggest"
    button -- classifies without writing anything, so a reviewer can see
    what the system would pick and still change it before saving.
    """
    known_families = sorted(
        {(e.get("family") or "Unclassified") for e in get_job_title_entries()} - {"Unclassified"}
    )
    family, method = classify_job_title_family(title, known_families)
    return {"family": family, "method": method}


def auto_classify_unclassified_job_titles() -> dict:
    """Runs every currently family="Unclassified" canonical title through
    classify_job_title_family and applies whatever it could place in one
    write -- the Job titles page's "Auto-classify unclassified" bulk
    action. Never blocks on a single title's LLM call failing; that
    title just stays unclassified, same as it already was.
    """
    entries = get_job_title_entries()
    known_families = sorted({(e.get("family") or "Unclassified") for e in entries} - {"Unclassified"})
    unclassified_titles = [e["title"] for e in entries if (e.get("family") or "Unclassified") == "Unclassified"]

    family_by_title: dict[str, str] = {}
    results: list[dict] = []

    for title in unclassified_titles:
        try:
            family, method = classify_job_title_family(title, known_families)
        except Exception:  # noqa: BLE001
            family, method = "Unclassified", "none"

        results.append({"title": title, "family": family, "method": method})
        if method != "none":
            family_by_title[title] = family

    write_result = bulk_apply_job_title_families(family_by_title) if family_by_title else {"updated_count": 0}

    return {
        "checked_count": len(unclassified_titles),
        "classified_count": write_result["updated_count"],
        "still_unclassified_count": len(unclassified_titles) - write_result["updated_count"],
        "results": results,
    }


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
