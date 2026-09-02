"""HERMES-900 daily taxonomy candidate triage.

Runs on a schedule (see ops/hermes-taxonomy-triage.service/.timer) to
clear the day's new skill/job-title taxonomy candidates automatically,
so a human never has to work through this queue by hand on a daily
basis. Two layers, in order:

1. Deterministic pre-filter -- candidates.py's _is_noise_skill_term/
   _is_noise_job_title already keep most junk (sentence fragments,
   person names, table rows) from ever being queued in the first
   place, so by the time this script runs, most of what's left is
   already a plausible term.

2. LLM batch classification -- whatever's still pending gets a real
   judgment call ("is this a genuine, nameable skill/job title, or
   still noise the deterministic filter didn't catch?"), in batches of
   ~40 terms per call rather than one call per term. On a real
   production backlog (2026-09), this batching brought a 2,300-item
   ambiguous set down to ~30 calls total.

Cost guardrail: MAX_PER_RUN caps how many candidates get processed in
a single run, oldest first -- if the backlog somehow spikes (a queue
processing bug, a burst of unusual mail), this bounds the worst-case
LLM spend for one run rather than processing an unbounded backlog.
Anything beyond the cap is left pending for the next scheduled run.

A batch that fails to parse an LLM response (after 3 retries) is left
pending rather than guessed at -- never silently auto-approved or
auto-rejected on an LLM hiccup.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from app.prompt_runtime.models import PromptRenderedMessage
from app.prompt_runtime.service import _call_litellm_with_model, litellm_configured
from app.understanding.taxonomy.candidates import (
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    list_taxonomy_candidates,
)

MODEL = os.getenv("HERMES_PROMPT_DEFAULT_MODEL", "anthropic/claude-haiku-4-5")
BATCH_SIZE = 40
MAX_PER_RUN = int(os.getenv("HERMES_TAXONOMY_TRIAGE_MAX_PER_RUN", "500"))

SKILL_SYSTEM_PROMPT = (
    "You are cleaning up an IT staffing recruitment platform's SKILLS taxonomy. "
    "You will get a numbered list of candidate terms pulled automatically from real "
    "job posting emails -- many are genuine technical skills/tools, but many are "
    "parsing noise: sentence fragments, person names, company names, city/location "
    "names, generic business phrases, HR labels, or garbled text. "
    "For EACH numbered item, decide APPROVE (it is a genuine, specific, nameable "
    "technical skill or tool a recruiter would list -- a technology, platform, "
    "certification, methodology, or programming concept) or REJECT (anything else: "
    "a person's name, company name, place name, sentence fragment, vague soft-skill "
    "phrase, HR/admin label, or garbled text). "
    "Reply with ONLY a JSON array of the strings \"approve\" or \"reject\", in the "
    "exact same order as the input, one entry per numbered item. No other text."
)

TITLE_SYSTEM_PROMPT = (
    "You are cleaning up an IT staffing recruitment platform's JOB TITLES taxonomy. "
    "You will get a numbered list of candidate terms pulled automatically from real "
    "job posting emails -- many are genuine job titles, but many are parsing noise: "
    "sentence fragments, person names, requirement-summary sentences, or garbled text. "
    "For EACH numbered item, decide APPROVE (it is a genuine, specific job title a "
    "recruiter would use -- possibly with a seniority/technology qualifier, e.g. "
    "'Senior SAP ABAP Developer') or REJECT (a person's name, a sentence, a vague "
    "phrase, or garbled text -- NOT a title). "
    "Reply with ONLY a JSON array of the strings \"approve\" or \"reject\", in the "
    "exact same order as the input, one entry per numbered item. No other text."
)


def _extract_json_array(text: str) -> list[str] | None:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [str(x).strip().lower() for x in parsed]


def classify_batch(terms: list[str], system_prompt: str) -> list[str]:
    # A term with an embedded newline or non-breaking space (a stray
    # parsing artifact from an older, already-queued candidate) turns
    # into an extra fake "line" in the numbered list below, throwing off
    # the model's item count and reliably producing a mismatched-length
    # response every retry -- confirmed against a real stuck batch in
    # production containing "HANA \xa0 \xa0 \xa0 \n\nRN SAP BOBJ Admin
    # Consultant". Collapsed to single spaces here, for prompting only;
    # the candidate's stored term is never modified.
    sanitized_terms = [re.sub(r"\s+", " ", t).strip() for t in terms]
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(sanitized_terms))
    messages = [
        PromptRenderedMessage(role="system", content=system_prompt),
        PromptRenderedMessage(role="user", content=numbered),
    ]

    for attempt in range(3):
        try:
            output, _usage = _call_litellm_with_model(messages, MODEL)
        except Exception as e:  # noqa: BLE001
            print(f"    LLM call failed (attempt {attempt + 1}): {e}")
            time.sleep(2)
            continue

        decisions = _extract_json_array(output)
        if decisions and len(decisions) == len(terms):
            return decisions

        print(f"    Bad/mismatched response (attempt {attempt + 1}): "
              f"got {len(decisions) if decisions else 0} decisions for {len(terms)} terms")
        time.sleep(2)

    return ["review"] * len(terms)


def triage(signal_type: str, system_prompt: str) -> dict:
    candidates = list_taxonomy_candidates(status="pending")
    candidates = [c for c in candidates if c["signal_type"] == signal_type]
    candidates.sort(key=lambda c: c["first_seen_at"])
    candidates = candidates[:MAX_PER_RUN]

    if not candidates:
        return {"processed": 0, "approved": 0, "rejected": 0, "left_for_review": 0}

    approve_ids: list[int] = []
    reject_ids: list[int] = []
    review_count = 0

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        terms = [c["term"] for c in batch]
        decisions = classify_batch(terms, system_prompt)

        for c, decision in zip(batch, decisions):
            if decision == "approve":
                approve_ids.append(c["id"])
            elif decision == "reject":
                reject_ids.append(c["id"])
            else:
                review_count += 1

        print(f"  {signal_type} batch {start}-{start + len(batch)}: "
              f"approve={len(approve_ids)} reject={len(reject_ids)} review={review_count}")

    approved = 0
    rejected = 0
    if approve_ids:
        result = bulk_approve_taxonomy_candidates(approve_ids, reviewed_by="hermes-daily-triage")
        approved = result["approved_count"]
        if result["failed"]:
            print(f"  {signal_type} approve failures: {result['failed'][:5]}")
    if reject_ids:
        result = bulk_reject_taxonomy_candidates(reject_ids, reviewed_by="hermes-daily-triage")
        rejected = result["rejected_count"]
        if result["failed"]:
            print(f"  {signal_type} reject failures: {result['failed'][:5]}")

    return {
        "processed": len(candidates),
        "approved": approved,
        "rejected": rejected,
        "left_for_review": review_count,
    }


def main() -> int:
    if not litellm_configured():
        print("LITELLM_API_KEY not configured -- skipping LLM triage this run "
              "(deterministic pre-filter in candidates.py still applies to new mail).")
        return 0

    print("=== HERMES-900 daily taxonomy triage ===")

    skill_summary = triage("skill", SKILL_SYSTEM_PROMPT)
    print(f"SKILLS: processed={skill_summary['processed']} "
          f"approved={skill_summary['approved']} rejected={skill_summary['rejected']} "
          f"left_for_review={skill_summary['left_for_review']}")

    title_summary = triage("job_title", TITLE_SYSTEM_PROMPT)
    print(f"TITLES: processed={title_summary['processed']} "
          f"approved={title_summary['approved']} rejected={title_summary['rejected']} "
          f"left_for_review={title_summary['left_for_review']}")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
