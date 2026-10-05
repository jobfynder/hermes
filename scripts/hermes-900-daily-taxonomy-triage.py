"""Evidence-gated, deterministic taxonomy and boilerplate maintenance.

No model call is permitted in this scheduled job. Clear noise is rejected;
technical terms and job titles are promoted only after recurring across
independent sender domains; ambiguous terms remain pending.
"""

from __future__ import annotations

import os
import re
import sys
from app.understanding.taxonomy.candidates import (
    _MIN_SKILL_REVIEW_OCCURRENCES,
    _MIN_SKILL_REVIEW_SENDERS,
    _MIN_TITLE_REVIEW_OCCURRENCES,
    _MIN_TITLE_REVIEW_SENDERS,
    _is_noise_job_title,
    _is_noise_skill_term,
    auto_classify_unclassified_job_titles,
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    list_taxonomy_candidates,
)
from app.understanding.taxonomy.skill_quality import skill_noise_reason
from app.understanding.taxonomy.title_family_classifier import classify_family_deterministically
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import get_canonical_skill_entries, set_skill_description
from app.runtime.db import cursor

MAX_PER_RUN = int(os.getenv("HERMES_TAXONOMY_TRIAGE_MAX_PER_RUN", "500"))
SKILL_SYSTEM_PROMPT = "deterministic"
TITLE_SYSTEM_PROMPT = "deterministic"


_TECHNICAL_SKILL_RE = re.compile(
    r"(?i)(?:\b(?:api|sdk|sql|nosql|aws|azure|gcp|sap|oracle|salesforce|servicenow|"
    r"workday|kubernetes|docker|python|java|javascript|typescript|node(?:\.js)?|react|"
    r"angular|linux|unix|terraform|ansible|kafka|snowflake|databricks|tableau|power\s*bi|"
    r"git(?:hub|lab)?|jenkins|devops|sre|ci\s*/?\s*cd|etl|iam|rbac|siem|soar|llm|"
    r"machine learning|artificial intelligence|nlp|database|cloud|network|cybersecurity|"
    r"security|automation|scripting|microservices?|middleware|observability|data pipeline)\b|"
    r"(?:\.net|c\+\+|c#))"
)
_TITLE_ROLE_RE = re.compile(
    r"(?i)\b(?:developer|engineer|architect|analyst|administrator|admin|manager|consultant|"
    r"lead|designer|researcher|technician|scientist|specialist|tester|coordinator|owner|"
    r"director|programmer|sme)\b"
)
_BLOCKED_TECH_ACRONYMS = {"USA", "US", "GC", "H1B", "C2C", "W2", "F2F", "ASAP"}


def deterministic_taxonomy_decision(candidate: dict) -> str:
    """Resolve only evidence-backed cases; ambiguous terms remain pending."""
    term = re.sub(r"\s+", " ", candidate.get("term") or "").strip()
    occurrences = int(candidate.get("occurrence_count") or 0)
    senders = len(candidate.get("distinct_senders") or [])
    signal_type = candidate.get("signal_type")

    if signal_type == "skill":
        if skill_noise_reason(term) or _is_noise_skill_term(term):
            return "reject"
        # An uppercase shape alone is not evidence of a technology: company
        # names, recruiter names and staffing acronyms have the same shape.
        technical_shape = bool(_TECHNICAL_SKILL_RE.search(term))
        return "approve" if (
            technical_shape
            and occurrences >= _MIN_SKILL_REVIEW_OCCURRENCES
            and senders >= _MIN_SKILL_REVIEW_SENDERS
        ) else "review"

    if signal_type == "job_title":
        if _is_noise_job_title(term):
            return "reject"
        family = classify_family_deterministically(term)
        return "approve" if (
            family and _TITLE_ROLE_RE.search(term)
            and occurrences >= _MIN_TITLE_REVIEW_OCCURRENCES
            and senders >= _MIN_TITLE_REVIEW_SENDERS
        ) else "review"

    return "review"


def triage(signal_type: str, _system_prompt: str) -> dict:
    candidates = list_taxonomy_candidates(
        status="pending", include_low_evidence_observations=True,
        signal_type=signal_type, least_recently_reviewed_first=True, limit=MAX_PER_RUN,
    )

    if not candidates:
        return {"processed": 0, "approved": 0, "rejected": 0, "left_for_review": 0}

    approve_ids: list[int] = []
    reject_ids: list[int] = []
    decisions = {c["id"]: deterministic_taxonomy_decision(c) for c in candidates}
    approve_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "approve"]
    reject_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "reject"]
    review_count = len(candidates) - len(approve_ids) - len(reject_ids)
    review_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "review"]

    approved = 0
    rejected = 0
    if approve_ids:
        result = bulk_approve_taxonomy_candidates(
            approve_ids, reviewed_by="hermes-daily-triage", allow_llm=False
        )
        approved = result["approved_count"]
        if result["failed"]:
            print(f"  {signal_type} approve failures: {result['failed'][:5]}")
    if reject_ids:
        result = bulk_reject_taxonomy_candidates(reject_ids, reviewed_by="hermes-daily-triage")
        rejected = result["rejected_count"]
        if result["failed"]:
            print(f"  {signal_type} reject failures: {result['failed'][:5]}")
    if review_ids:
        # A pending row remains eligible if future sightings strengthen its
        # evidence. Recording the pass lets the next run examine a different
        # page instead of reconsidering the same ambiguous rows forever.
        with cursor() as cur:
            cur.execute(
                "UPDATE taxonomy_candidates SET reviewed_at=now(), reviewed_by='hermes-deferred-observation' "
                "WHERE id=ANY(%s) AND status='pending'",
                (review_ids,),
            )

    return {
        "processed": len(candidates),
        "approved": approved,
        "rejected": rejected,
        "left_for_review": review_count,
    }


_SAFE_BOILERPLATE_EXACT = {
    "requirements", "required qualifications", "preferred qualifications",
    "responsibilities", "roles and responsibilities", "job responsibilities",
    "job description", "position summary", "about the role", "what you will do",
    "what you'll do", "what we are looking for", "skills and qualifications",
    "education and experience", "additional information", "equal opportunity employer",
}
_SAFE_BOILERPLATE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"^to (?:apply|be considered),? please (?:send|submit|share).{0,140}(?:resume|cv)",
    r"^please (?:send|submit|share).{0,140}(?:resume|cv).{0,80}(?:rate|availability|contact)?$",
    r"^(?:click here|unsubscribe|manage (?:your )?preferences|view in browser)",
    r"^(?:this email|this message).{0,180}(?:confidential|intended recipient)",
    r"^(?:we are|our company is) an equal opportunity employer",
    r"^equal (?:employment )?opportunity.{0,180}$",
    r"^(?:strong|excellent) (?:written and verbal )?(?:communication|analytical|problem[- ]solving|organizational|time[- ]management|interpersonal|presentation)(?: and (?:communication|analytical|problem[- ]solving|organizational|time[- ]management|interpersonal|presentation))* (?:skills|abilities|capabilities)[.!]?$",
    r"^ability to manage multiple priorities in a fast[- ]paced environment[.!]?$",
    r"^perform other related duties as assigned[.!]?$",
    r"^(?:reply to|e-?mail|phone|web(?:site)?|address)\s*:\s*\S+",
    r"^(?:please|kindly).{0,80}(?:find|review|go through|have a look).{0,100}(?:job description|requirement|jd)\b",
    r"^(?:please|kindly).{0,160}(?:send|share|forward|revert).{0,80}(?:resume|profile|cv)\b",
    r"^(?:i hope|hope) (?:this email finds you|you are|you'?re) .{0,100}$",
    r"^(?:sign-up for your account with .{0,80} recruiting portal|hire our it recruiter at .{0,80})$",
    r"^(?:an early response is .{0,80}|due to the urgent nature .{0,140})$",
))
_SPECIFIC_REQUIREMENT_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b\d+\+?\s*(?:years?|yrs?)\b",
    r"^(?:job title|location|rate|skills?|technology|certification)\s*:",
    r"\b(?:bachelor'?s|master'?s|phd|degree|certification|certified)\b",
    r"\b(?:experience with|experience in|hands[- ]on|proficiency in|knowledge of)\b",
    r"^(?:architect|build|configure|coordinate|create|develop|implement|lead|manage|provide|support|track|troubleshoot|work with)\b",
))


def deterministic_boilerplate_decision(term: str) -> str:
    """Approve only high-precision template lines. Ambiguous lines stay pending."""
    cleaned = re.sub(r"\s+", " ", term or "").strip()
    normalized = cleaned.casefold().strip(" :-–—.!")
    if normalized in _SAFE_BOILERPLATE_EXACT:
        return "approve"
    if any(pattern.search(cleaned) for pattern in _SAFE_BOILERPLATE_PATTERNS):
        return "approve"
    # Rejecting here is conservative: it only keeps genuine requirement
    # content in job descriptions and removes it from the boilerplate queue.
    # It never strips the line from an email.
    if len(cleaned) > 220 or cleaned.startswith(("•", "●", "▪", "- ")):
        return "reject"
    if any(pattern.search(cleaned) for pattern in _SPECIFIC_REQUIREMENT_PATTERNS):
        return "reject"
    return "review"


def triage_boilerplate_deterministically() -> dict:
    candidates = list_taxonomy_candidates(
        status="pending", include_boilerplate_observations=False,
        include_low_evidence_observations=False, signal_type="boilerplate_line",
        least_recently_reviewed_first=True, limit=MAX_PER_RUN,
    )
    decisions = {c["id"]: deterministic_boilerplate_decision(c["term"]) for c in candidates}
    approve_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "approve"]
    reject_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "reject"]
    approved = 0
    if approve_ids:
        result = bulk_approve_taxonomy_candidates(
            approve_ids, reviewed_by="hermes-daily-deterministic", allow_llm=False
        )
        approved = result["approved_count"]
    rejected = 0
    if reject_ids:
        result = bulk_reject_taxonomy_candidates(reject_ids, reviewed_by="hermes-daily-deterministic")
        rejected = result["rejected_count"]
    review_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "review"]
    if review_ids:
        with cursor() as cur:
            cur.execute(
                "UPDATE taxonomy_candidates SET reviewed_at=now(), reviewed_by='hermes-deferred-observation' "
                "WHERE id=ANY(%s) AND status='pending'",
                (review_ids,),
            )
    return {"processed": len(candidates), "approved": approved, "rejected": rejected,
            "left_for_review": len(candidates) - len(approve_ids) - len(reject_ids)}


def prune_stale_boilerplate_observations(limit: int = 20000) -> int:
    """Retire one-off lines after 14 days so observation storage stays bounded."""
    with cursor() as cur:
        cur.execute(
            "WITH stale AS (SELECT id FROM taxonomy_candidates "
            "WHERE signal_type='boilerplate_line' AND status='pending' "
            "AND occurrence_count < 3 AND jsonb_array_length(distinct_senders) < 2 "
            "AND last_seen_at < now()-interval '14 days' ORDER BY last_seen_at LIMIT %s) "
            "UPDATE taxonomy_candidates t SET status='rejected', reviewed_at=now(), "
            "reviewed_by='hermes-stale-observation' FROM stale WHERE t.id=stale.id",
            (min(max(limit, 1), 50000),),
        )
        return cur.rowcount


def backfill_missing_descriptions() -> dict:
    """Retry descriptions from the curated glossary without any model call."""
    missing = [entry for entry in get_canonical_skill_entries() if not (entry.get("description") or "").strip()]
    deterministic_filled = 0
    still_missing = []
    for entry in missing:
        description = generate_skill_description(entry["name"], category=entry.get("category"), allow_llm=False)
        if description and set_skill_description(entry["name"], description, source="ai_generated"):
            deterministic_filled += 1
        else:
            still_missing.append(entry)

    llm_enabled = False
    llm_filled = 0
    llm_failed = 0
    return {"missing_before": len(missing), "deterministic_filled": deterministic_filled,
            "llm_enabled": llm_enabled and litellm_configured(), "llm_filled": llm_filled,
            "llm_failed": llm_failed, "remaining": len(missing) - deterministic_filled - llm_filled}


def main() -> int:
    print("=== HERMES-900 daily taxonomy triage ===")

    skill_summary = triage("skill", SKILL_SYSTEM_PROMPT)
    print(f"SKILLS: processed={skill_summary['processed']} "
          f"approved={skill_summary['approved']} rejected={skill_summary['rejected']} "
          f"left_for_review={skill_summary['left_for_review']}")

    title_summary = triage("job_title", TITLE_SYSTEM_PROMPT)
    print(f"TITLES: processed={title_summary['processed']} "
          f"approved={title_summary['approved']} rejected={title_summary['rejected']} "
          f"left_for_review={title_summary['left_for_review']}")

    family_summary = auto_classify_unclassified_job_titles()
    print(f"TITLE FAMILIES: checked={family_summary['checked_count']} "
          f"classified={family_summary['classified_count']} "
          f"still_unclassified={family_summary['still_unclassified_count']} method=deterministic")

    boilerplate_summary = triage_boilerplate_deterministically()
    print(f"BOILERPLATE: processed={boilerplate_summary['processed']} "
          f"approved={boilerplate_summary['approved']} rejected={boilerplate_summary['rejected']} "
          f"left_for_review={boilerplate_summary['left_for_review']}")
    print(f"BOILERPLATE_STALE_RETIRED: {prune_stale_boilerplate_observations()}")

    description_summary = backfill_missing_descriptions()
    print(f"DESCRIPTIONS: missing_before={description_summary['missing_before']} "
          f"deterministic_filled={description_summary['deterministic_filled']} "
          f"llm_enabled={description_summary['llm_enabled']} llm_filled={description_summary['llm_filled']} "
          f"llm_failed={description_summary['llm_failed']} remaining={description_summary['remaining']}")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
