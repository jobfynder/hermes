"""Evidence-gated, deterministic taxonomy and boilerplate maintenance.

No model call is permitted in this scheduled job. Clear noise is rejected;
technical terms and job titles are promoted only after recurring across
independent sender domains; ambiguous terms remain pending.
"""

from __future__ import annotations

import os
import re
import sys
import argparse
import json
import time
import signal
from contextlib import contextmanager
from datetime import datetime, UTC
from pathlib import Path
from app.understanding.taxonomy.candidates import (
    _MIN_SKILL_REVIEW_OCCURRENCES,
    _MIN_SKILL_REVIEW_SENDERS,
    _MIN_TITLE_REVIEW_OCCURRENCES,
    _MIN_TITLE_REVIEW_SENDERS,
    _MIN_BOILERPLATE_DISTINCT_SENDERS,
    approve_taxonomy_candidate,
    _is_noise_job_title,
    _is_noise_skill_term,
    auto_classify_unclassified_job_titles,
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    list_taxonomy_candidates,
    retire_known_taxonomy_candidates,
)
from app.understanding.taxonomy import triage_rules
from app.understanding.taxonomy.skill_quality import skill_noise_reason
from app.understanding.taxonomy.title_family_classifier import classify_family_deterministically
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import get_canonical_skill_entries, set_skill_description, normalize_taxonomy_key
from app.runtime.db import cursor, get_pool

MAX_PER_RUN = min(max(int(os.getenv("HERMES_TAXONOMY_TRIAGE_MAX_PER_RUN", "5000")), 1), 20000)
MAX_SKILL_APPROVALS = 100
MAX_TITLE_APPROVALS = 25
POLICY_VERSION = 'hermes-auto-v3'
RUNNER_VERSION = 'taxonomy-automation-2.2'
DRY_RUN = False


class RunDeadlineExceeded(BaseException):
    """Must escape best-effort helpers that catch ordinary Exception."""


class TriageBatchError(RuntimeError):
    def __init__(self, failures):
        self.reason_counts = {}
        for item in failures:
            reason = item.get('reason') or 'unspecified'
            self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1


def check_batch_result(result):
    """A concurrent reviewer winning the race is success, not an outage."""
    failures = [f for f in result.get('failed', [])
                if f.get('reason') != 'candidate_not_found_or_already_reviewed']
    if failures:
        raise TriageBatchError(failures)
    return len(result.get('failed', []))


_CATALOG_PATH = Path(__file__).with_name('hermes-taxonomy-skill-catalog.json')
SKILL_CATALOG = {normalize_taxonomy_key(e['name']): e for e in json.loads(_CATALOG_PATH.read_text())['skills']}
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


def pending_batch(signal_type):
    """Review new evidence once per policy version; prioritize credible terms.

    The old queue repeatedly spent its quota on unchanged ambiguous terms.
    These existing columns provide a durable cursor across process restarts.
    No table migration or Codex automation is needed.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT id,term,signal_type,occurrence_count,distinct_senders FROM taxonomy_candidates "
            "WHERE status='pending' AND signal_type=%s "
            "AND (reviewed_by IS DISTINCT FROM %s OR reviewed_at IS NULL OR last_seen_at>reviewed_at) "
            "AND (%s <> 'boilerplate_line' OR jsonb_array_length(distinct_senders)>=%s) "
            "ORDER BY CASE WHEN occurrence_count>=%s AND jsonb_array_length(distinct_senders)>=%s THEN 0 ELSE 1 END, "
            "reviewed_at ASC NULLS FIRST,id ASC LIMIT %s",
            (signal_type, POLICY_VERSION, signal_type, _MIN_BOILERPLATE_DISTINCT_SENDERS,
             _MIN_SKILL_REVIEW_OCCURRENCES if signal_type == 'skill' else _MIN_TITLE_REVIEW_OCCURRENCES,
             _MIN_SKILL_REVIEW_SENDERS if signal_type == 'skill' else _MIN_TITLE_REVIEW_SENDERS,
             MAX_PER_RUN),
        )
        return [dict(r) for r in cur.fetchall()]


def defer_candidates(candidate_ids):
    if candidate_ids and not DRY_RUN:
        with cursor() as cur:
            cur.execute("UPDATE taxonomy_candidates SET reviewed_at=now(),reviewed_by=%s "
                        "WHERE id=ANY(%s) AND status='pending'", (POLICY_VERSION, candidate_ids))


def catalog_entry(term):
    return SKILL_CATALOG.get(normalize_taxonomy_key(term))


def deterministic_description(term, category=None):
    entry = catalog_entry(term)
    return entry['description'] if entry else generate_skill_description(term, category=category, allow_llm=False)


def deterministic_taxonomy_decision(candidate: dict) -> str:
    """First tier (certain cases) then second tier (shared rules in
    app.understanding.taxonomy.triage_rules, also used by the dashboard to
    explain its suggestion). Only genuinely ambiguous terms stay 'review'."""
    decision = _first_tier_taxonomy_decision(candidate)
    if decision != 'review' or candidate.get('signal_type') != 'skill':
        return decision
    term = candidate.get('term') or ''
    return triage_rules.skill_decision(term, catalogued=bool(catalog_entry(term)))[0]


def _first_tier_taxonomy_decision(candidate: dict) -> str:
    """Resolve only evidence-backed cases; ambiguous terms remain pending."""
    term = re.sub(r"\s+", " ", candidate.get("term") or "").strip()
    occurrences = int(candidate.get("occurrence_count") or 0)
    senders = len(candidate.get("distinct_senders") or [])
    signal_type = candidate.get("signal_type")

    if signal_type == "skill":
        if re.match(r'(?i)^(?:along with|practical understanding of|technical fluency across|participate in|role descriptions:)\b', term):
            return 'reject'
        if re.search(r'(?i)^(?:desk\s*(?:no|number)|telephone|phone)\s*[:.]|\b\d{3}[- .]\d{3}[- .]\d{4}\b', term):
            return 'reject'
        if skill_noise_reason(term) or _is_noise_skill_term(term):
            return "reject"
        # An uppercase shape alone is not evidence of a technology: company
        # names, recruiter names and staffing acronyms have the same shape.
        technical_shape = bool(_TECHNICAL_SKILL_RE.search(term) or catalog_entry(term)
                               or deterministic_description(term))
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
    candidates = pending_batch(signal_type)

    if not candidates:
        return {"processed": 0, "approved": 0, "rejected": 0, "left_for_review": 0}

    approve_ids: list[int] = []
    reject_ids: list[int] = []
    decisions = {c["id"]: deterministic_taxonomy_decision(c) for c in candidates}
    approve_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "approve"]
    approval_limit = MAX_SKILL_APPROVALS if signal_type == 'skill' else MAX_TITLE_APPROVALS
    approval_budget_deferred = max(0, len(approve_ids) - approval_limit)
    approve_ids = approve_ids[:approval_limit]
    reject_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "reject"]
    review_count = len(candidates) - len(approve_ids) - len(reject_ids)
    review_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "review"]

    approved = 0
    rejected = 0
    concurrent_reviews = 0
    if DRY_RUN:
        return {'processed': len(candidates), 'approved': 0, 'rejected': 0,
                'would_approve': len(approve_ids), 'would_reject': len(reject_ids), 'left_for_review': review_count,
                'approval_budget_deferred': approval_budget_deferred}
    if approve_ids:
        curated = [c for c in candidates if c['id'] in approve_ids and signal_type == 'skill' and catalog_entry(c['term'])]
        for candidate in curated:
            entry = catalog_entry(candidate['term'])
            result = approve_taxonomy_candidate(candidate['id'], category=entry['category'],
                                               reviewed_by=POLICY_VERSION, allow_llm=False)
            if not result.get('approved'):
                if result.get('reason') == 'candidate_not_found_or_already_reviewed':
                    concurrent_reviews += 1
                    continue
                raise TriageBatchError([result])
            existing = next((e for e in get_canonical_skill_entries()
                             if normalize_taxonomy_key(e['name']) == normalize_taxonomy_key(candidate['term'])), None)
            if existing and not existing.get('description') and existing.get('description_source') != 'human_edited':
                set_skill_description(candidate['term'], entry['description'], source='deterministic_catalog')
            approved += 1
        approve_ids = [i for i in approve_ids if i not in {c['id'] for c in curated}]
        result = bulk_approve_taxonomy_candidates(
            approve_ids, reviewed_by=POLICY_VERSION, allow_llm=False
        )
        approved += result["approved_count"]
        concurrent_reviews += check_batch_result(result)
    if reject_ids:
        result = bulk_reject_taxonomy_candidates(reject_ids, reviewed_by="hermes-daily-triage")
        rejected = result["rejected_count"]
        concurrent_reviews += check_batch_result(result)
    defer_candidates(review_ids)

    return {
        "processed": len(candidates),
        "approved": approved,
        "rejected": rejected,
        "left_for_review": review_count,
        "concurrent_reviews": concurrent_reviews,
        "approval_budget_deferred": approval_budget_deferred,
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
    decision = _first_tier_boilerplate_decision(term)
    return decision if decision != 'review' else triage_rules.boilerplate_decision(term)[0]


def _first_tier_boilerplate_decision(term: str) -> str:
    """Approve only high-precision template lines. Ambiguous lines stay pending."""
    cleaned = re.sub(r"\s+", " ", term or "").strip()
    normalized = cleaned.casefold().strip(" :-–—.!")
    if normalized in _SAFE_BOILERPLATE_EXACT:
        return "approve"
    # A footer-shaped sentence can still carry a real requirement.
    if any(pattern.search(cleaned) for pattern in _SPECIFIC_REQUIREMENT_PATTERNS):
        return 'reject'
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
    candidates = pending_batch('boilerplate_line')
    decisions = {c["id"]: deterministic_boilerplate_decision(c["term"]) for c in candidates}
    approve_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "approve"]
    reject_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "reject"]
    approved = 0
    concurrent_reviews = 0
    if DRY_RUN:
        return {'processed': len(candidates), 'approved': 0, 'rejected': 0,
                'would_approve': len(approve_ids), 'would_reject': len(reject_ids),
                'left_for_review': len(candidates)-len(approve_ids)-len(reject_ids)}
    if approve_ids:
        result = bulk_approve_taxonomy_candidates(
            approve_ids, reviewed_by="hermes-daily-deterministic", allow_llm=False
        )
        approved = result["approved_count"]
        concurrent_reviews += check_batch_result(result)
    rejected = 0
    if reject_ids:
        result = bulk_reject_taxonomy_candidates(reject_ids, reviewed_by="hermes-daily-deterministic")
        rejected = result["rejected_count"]
        concurrent_reviews += check_batch_result(result)
    review_ids = [candidate_id for candidate_id, decision in decisions.items() if decision == "review"]
    defer_candidates(review_ids)
    return {"processed": len(candidates), "approved": approved, "rejected": rejected,
            "left_for_review": len(candidates) - len(approve_ids) - len(reject_ids),
            "concurrent_reviews": concurrent_reviews}


def prune_stale_boilerplate_observations(limit: int = 20000) -> int:
    """Retire one-off lines after 14 days so observation storage stays bounded."""
    if DRY_RUN:
        return 0
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
    missing = [entry for entry in get_canonical_skill_entries()
               if not (entry.get("description") or "").strip() and entry.get('description_source') != 'human_edited']
    deterministic_filled = 0
    still_missing = []
    for entry in missing:
        description = deterministic_description(entry["name"], category=entry.get("category"))
        if description and (DRY_RUN or set_skill_description(entry["name"], description, source="deterministic_catalog")):
            deterministic_filled += 1
        else:
            still_missing.append(entry)

    llm_enabled = False
    llm_filled = 0
    llm_failed = 0
    return {"missing_before": len(missing), "deterministic_filled": 0 if DRY_RUN else deterministic_filled,
            "would_fill": deterministic_filled if DRY_RUN else 0,
            "llm_enabled": False, "llm_filled": llm_filled,
            "llm_failed": llm_failed, "remaining": len(missing) - deterministic_filled - llm_filled}


@contextmanager
def singleton():
    # Reuse the same session advisory-lock pattern as the Backfill worker.
    with get_pool().connection() as conn:
        conn.autocommit = True
        acquired = conn.execute('SELECT pg_try_advisory_lock(892310485)').fetchone()[0]
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute('SELECT pg_advisory_unlock(892310485)')


def run_stages(max_seconds=600):
    started = time.monotonic()
    stages = [
        ('known_duplicates', lambda: {'dry_run': True} if DRY_RUN else
         {'retired_count': retire_known_taxonomy_candidates()['retired_count']}),
        ('skills', lambda: triage('skill', SKILL_SYSTEM_PROMPT)),
        ('boilerplate', triage_boilerplate_deterministically),
        ('stale_boilerplate', lambda: {'retired_count': prune_stale_boilerplate_observations()}),
        ('descriptions', backfill_missing_descriptions),
        ('titles', lambda: triage('job_title', TITLE_SYSTEM_PROMPT)),
        ('title_families', lambda: {'dry_run': True} if DRY_RUN else
         {k: v for k, v in auto_classify_unclassified_job_titles(allow_llm=False).items() if k != 'results'}),
    ]
    results = {}
    failed = False
    for name, execute in stages:
        if time.monotonic() - started >= max_seconds:
            results[name] = {'error': 'run_budget_exceeded'}
            failed = True
            continue
        try:
            results[name] = execute()
        except (Exception, RunDeadlineExceeded) as exc:
            # One failure must not prevent independent queue maintenance.
            # Do not put terms, signatures or credentials in scheduler logs.
            results[name] = {'error': type(exc).__name__}
            if isinstance(exc, TriageBatchError):
                results[name]['failure_reasons'] = exc.reason_counts
            failed = True
        print(json.dumps({'stage': name, **results[name]}), flush=True)
    return results, failed


def main(argv=None) -> int:
    global DRY_RUN, MAX_PER_RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-per-run', type=int, default=MAX_PER_RUN)
    parser.add_argument('--max-seconds', type=int, default=600)
    parser.add_argument('--status-file', default=os.getenv('HERMES_TAXONOMY_TRIAGE_STATUS_FILE'))
    args = parser.parse_args(argv)
    if not 1 <= args.max_per_run <= 20000 or not 1 <= args.max_seconds <= 900:
        parser.error('max-per-run must be 1..20000 and max-seconds 1..900')
    DRY_RUN, MAX_PER_RUN = args.dry_run, args.max_per_run
    started_at = datetime.now(UTC).isoformat()
    def timeout(_signum, _frame):
        raise RunDeadlineExceeded()
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(args.max_seconds)
    try:
        with singleton() as acquired:
            if not acquired:
                print(json.dumps({'status': 'already_running', 'policy': POLICY_VERSION}))
                return 0
            results, failed = run_stages(args.max_seconds)
    except RunDeadlineExceeded:
        results, failed = {'run': {'error': 'run_budget_exceeded'}}, True
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    summary = {'policy': POLICY_VERSION, 'runner_version': RUNNER_VERSION, 'started_at': started_at,
               'finished_at': datetime.now(UTC).isoformat(), 'dry_run': DRY_RUN,
               'status': 'failed' if failed else 'success', 'results': results}
    if args.status_file and not DRY_RUN:
        path = Path(args.status_file)
        try:
            last = json.loads(path.read_text())
        except (OSError, ValueError):
            last = {}
        summary['last_success_at'] = last.get('last_success_at') if failed else summary['finished_at']
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(summary, indent=2))
        os.replace(temporary, path)
    print(json.dumps(summary), flush=True)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
