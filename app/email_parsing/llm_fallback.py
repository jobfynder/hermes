"""LLM extraction fallback for email parsing (spec section 7.5, step 7).

Deterministic parsing (app/email_parsing/parsers.py) always runs first
and stays 100% LLM-free -- this module is a strictly separate, later
stage that only engages when the deterministic parser's own confidence
lands below FALLBACK_CONFIDENCE_THRESHOLD (the same 0.70 cutoff those
parsers already use for requires_review, so "needs a second pass" and
"needs human review if it doesn't get one" are the same line).

Reuses the exact same audited, cost-tracked, cache-eligible LiteLLM/
Langfuse path (run_llm_fallback) other Hermes capabilities already call,
and the *same Langfuse prompts* that already exist for near-identical
jobs: jf.jobs.jd.extract (used by the generic /understanding pipeline
for job descriptions) and jf.broadcast.hotlist.extract (used by the
Telegram broadcast channel's own confidence-gated hotlist fallback --
see app/channels/broadcast_extraction.py, which this module's design
mirrors). Two email-specific document kinds, zero new prompts, one
already-proven fallback mechanism.

Anti-hallucination guarantee (spec section 13.2): a job-requirement
field the deterministic parser already found is never overwritten by
the LLM -- only genuinely empty fields get filled. A low-confidence
hotlist split, by contrast, usually means the record *boundaries* are
wrong (wrong number of consultants, fields attributed to the wrong
person), not just a few missing fields -- there merging per-field
doesn't make sense, so a used LLM result replaces the whole record list
instead, matching broadcast_extraction.py's own hotlist handling.
"""

from __future__ import annotations

import json
from typing import Any

from app.prompt_runtime.extraction_fallback import run_llm_fallback

# Matches parse_requirement_email/parse_hotlist_email's own requires_review
# cutoff (app/email_parsing/parsers.py) -- "needs a second pass" and "needs
# human review if it doesn't get one" are deliberately the same threshold.
FALLBACK_CONFIDENCE_THRESHOLD = 0.70

JOB_REQUIREMENT_FIELDS = (
    "job_title",
    "company",
    "linkedin_url",
    "required_skills",
    "preferred_skills",
    "years_of_experience",
    "location",
    "work_authorization",
    "employment_type",
    "rate_or_salary",
)

HOTLIST_CONSULTANT_FIELDS = (
    "candidate_name",
    "candidate_email",
    "candidate_phone",
    "primary_job_title",
    "primary_skills",
    "years_of_experience",
    "current_location",
    "work_authorization",
    "availability",
    "expected_rate",
)

JOB_SCHEMA_HINT = json.dumps({field: "string|null" for field in JOB_REQUIREMENT_FIELDS} | {
    "required_skills": ["string"],
    "preferred_skills": ["string"],
    "years_of_experience": "number|null",
})

HOTLIST_SCHEMA_HINT = json.dumps(
    {
        "consultants": [
            {field: "string|null" for field in HOTLIST_CONSULTANT_FIELDS}
            | {"primary_skills": ["string"], "years_of_experience": "number|null"}
        ]
    }
)

JOB_FALLBACK_PROMPT_ID = "jf.jobs.jd.extract"
HOTLIST_FALLBACK_PROMPT_ID = "jf.broadcast.hotlist.extract"


def _empty_job_record() -> dict[str, Any]:
    return {
        "record_type": "job_requirement",
        "job_title": None,
        "job_description": None,
        "company": None,
        "linkedin_url": None,
        "required_skills": [],
        "preferred_skills": [],
        "years_of_experience": None,
        "location": None,
        "work_authorization": None,
        "employment_type": None,
        "rate_or_salary": None,
        "source_section": 1,
        "parse_confidence": 0.0,
        "requires_review": True,
        "warnings": [],
    }


def apply_job_requirement_fallback(clean_text: str, email_parsing: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Fills only the null/missing fields on the (single, for email) job-
    requirement record via LLM. Returns the possibly-updated result and
    the set of field names the LLM actually filled, so the caller can
    tag exactly those fields' provenance as llm_fallback -- everything
    else in the record stays attributed to the deterministic parser,
    because it was.
    """
    if email_parsing.get("confidence", 0.0) >= FALLBACK_CONFIDENCE_THRESHOLD:
        return email_parsing, set()

    records = email_parsing.get("records") or []
    record = records[0] if records else _empty_job_record()

    outcome = run_llm_fallback(
        prompt_id=JOB_FALLBACK_PROMPT_ID,
        variables={"clean_jd": clean_text, "job_schema": JOB_SCHEMA_HINT, "taxonomy_subset": "[]"},
        source="email_requirement_extract",
    )
    email_parsing["llm_fallback"] = {
        "used": outcome.get("used", False),
        "prompt_id": outcome.get("prompt_id"),
        "reason": outcome.get("reason"),
    }

    if not outcome.get("used"):
        return email_parsing, set()

    extracted = outcome["extracted"]
    filled_fields: set[str] = set()

    for field in JOB_REQUIREMENT_FIELDS:
        current = record.get(field)
        is_empty = current in (None, "", [])
        new_value = extracted.get(field)
        has_new_value = new_value not in (None, "", [])

        if is_empty and has_new_value:
            record[field] = new_value
            filled_fields.add(field)

    if filled_fields:
        record["parse_confidence"] = max(record.get("parse_confidence", 0.0), 0.75)
        record["requires_review"] = record["parse_confidence"] < FALLBACK_CONFIDENCE_THRESHOLD
        record["warnings"] = [w for w in record.get("warnings", []) if "missing" not in w]

        email_parsing["records"] = [record]
        email_parsing["record_count"] = 1
        email_parsing["confidence"] = record["parse_confidence"]
        email_parsing["requires_review"] = record["requires_review"]
        email_parsing["llm_filled_fields"] = sorted(filled_fields)

    return email_parsing, filled_fields


def apply_hotlist_fallback(clean_text: str, email_parsing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Whole-message re-extraction when the deterministic table/block
    parse scored low. Returns the possibly-updated result and whether the
    LLM path actually produced a usable replacement, so the caller can
    tag every field in every resulting record as llm_fallback.
    """
    if email_parsing.get("confidence", 0.0) >= FALLBACK_CONFIDENCE_THRESHOLD:
        return email_parsing, False

    outcome = run_llm_fallback(
        prompt_id=HOTLIST_FALLBACK_PROMPT_ID,
        variables={"hotlist_schema": HOTLIST_SCHEMA_HINT, "message": clean_text},
        source="email_hotlist_extract",
    )
    email_parsing["llm_fallback"] = {
        "used": outcome.get("used", False),
        "prompt_id": outcome.get("prompt_id"),
        "reason": outcome.get("reason"),
    }

    if not outcome.get("used"):
        return email_parsing, False

    consultants = outcome["extracted"].get("consultants") or []
    if not consultants:
        return email_parsing, False

    new_records = []
    for ordinal, consultant in enumerate(consultants, start=1):
        record = {"record_type": "consultant_hotlist"}
        for field in HOTLIST_CONSULTANT_FIELDS:
            value = consultant.get(field)
            record[field] = value if field != "primary_skills" else (value or [])
        record.update(
            {
                "source_row": ordinal,
                "parse_confidence": 0.75,
                "requires_review": False,
                "warnings": [],
            }
        )
        new_records.append(record)

    email_parsing["records"] = new_records
    email_parsing["record_count"] = len(new_records)
    email_parsing["confidence"] = 0.75
    email_parsing["requires_review"] = False
    email_parsing["warnings"] = []

    return email_parsing, True
