"""Pushes a PUBLISHED job-requirement draft to Jobfynder Core's job board.

This is the very last step of the pipeline: email -> parsed -> landed in
Hermes's own database -> (claim-and-verify confirmed, or manually
approved) -> published in Hermes -> *only then* -> pushed here. Nothing
before "published" ever reaches Core -- matches the "Hermes proposes,
Core executes" boundary (docs/hermes-architecture-frozen-v1.md section 2).

Calls Core's existing internal endpoint, POST /api/hermes/job/create
(HermesAuthGuard: shared-secret bearer token, not a user login -- see
jobFynder-BE-nestJS src/hermes/hermes-auth.guard.ts). That endpoint
always creates the job as DRAFT on Core's side too (JobStatus.DRAFT) --
this push does not publish anything live on the job board by itself;
Core's own separate publish step still gates that. Two independent
"nothing goes live automatically" guarantees, not one.

Every job is attributed to a fixed system account on Core
(HERMES_SOURCING_USER_ID, migration 20260829010000) -- the real external
recruiter is captured via externalSource/recruiterInfo, not by
impersonating them. See that migration's comment in the Core repo for
why this isn't an unclaimed-contact row.

Best-effort field mapping: Hermes extracts free-text fields (a raw
location string, a raw rate string, a raw employment-type string); Core
expects some of those pre-classified against its own taxonomy tables
(employment types, skills, experience levels) with case-insensitive
exact matching. A field Hermes sends that doesn't match Core's taxonomy
comes back in Core's own unmatchedFields report rather than silently
being dropped or guessed into place -- recorded here, not hidden.
Employment type is the one hard requirement Core enforces (a job posting
needs at least one) -- if Hermes never determined one, the push fails
loudly with that exact reason rather than inventing "Contract" out of
thin air.

Never raises: a push failure must not break the publish it followed --
it is recorded in core_pushes (app/runtime/db.py) as a failed attempt,
visible for retry or manual follow-up, exactly like any other fallible
step in this pipeline.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.drafts.models import DraftObject
from app.runtime.db import cursor

CORE_API_BASE_URL = os.getenv("CORE_API_BASE_URL", "").rstrip("/")
HERMES_SERVICE_TOKEN = os.getenv("HERMES_SERVICE_TOKEN", "")

_RATE_RE = re.compile(
    r"\$\s?(?P<min>\d[\d,]*(?:\.\d+)?)\s*(?:-|to)?\s*\$?(?P<max>\d[\d,]*(?:\.\d+)?)?\s*"
    r"(?:/|per\s*)?\s*(?P<unit>hr|hour|day|month|mo|yr|year|annual|k)?",
    re.IGNORECASE,
)

_RATE_UNIT_MAP = {
    "hr": "PER_HOUR", "hour": "PER_HOUR",
    "day": "PER_DAY",
    "month": "PER_MONTH", "mo": "PER_MONTH",
    "yr": "ANNUAL", "year": "ANNUAL", "annual": "ANNUAL", "k": "ANNUAL",
}

_WORK_MODE_RE = re.compile(r"\b(remote|onsite|on-site|hybrid)\b", re.IGNORECASE)


def core_push_configured() -> bool:
    return bool(CORE_API_BASE_URL and HERMES_SERVICE_TOKEN)


def _parse_rate(rate_raw: str | None) -> dict[str, Any]:
    """Best-effort: '$65/hr' -> minRate=65, rateType=PER_HOUR. Returns an
    empty dict for anything it can't confidently parse -- Core's DTO
    defaults rateType and leaves rates optional, so an empty dict is a
    safe, valid contribution to the payload, not a failure.
    """
    if not rate_raw:
        return {}

    match = _RATE_RE.search(rate_raw)
    if not match or not match.group("min"):
        return {}

    result: dict[str, Any] = {}
    unit_lower = (match.group("unit") or "").lower()

    try:
        min_rate = float(match.group("min").replace(",", ""))
        if unit_lower == "k":
            min_rate *= 1000
        result["minRate"] = min_rate

        if match.group("max"):
            max_rate = float(match.group("max").replace(",", ""))
            if unit_lower == "k":
                max_rate *= 1000
            result["maxRate"] = max_rate
    except ValueError:
        return {}

    if unit_lower in _RATE_UNIT_MAP:
        result["rateType"] = _RATE_UNIT_MAP[unit_lower]

    return result


def _parse_location(location_raw: str | None) -> dict[str, Any]:
    """Best-effort: 'Burlington, MA (100% Onsite)' -> city, state,
    workLocation. workLocation defaults to ONSITE (Core requires some
    value and this is the historically dominant case for staffing
    emails) only when the text gives no work-mode signal at all --
    when it does, that signal always wins.
    """
    result: dict[str, Any] = {}
    text = location_raw or ""

    mode_match = _WORK_MODE_RE.search(text)
    if mode_match:
        mode = mode_match.group(1).lower().replace("-", "")
        result["workLocation"] = {"remote": "REMOTE", "onsite": "ONSITE", "hybrid": "HYBRID"}[mode]
    else:
        result["workLocation"] = "ONSITE"

    city_state = re.sub(r"\([^)]*\)", "", text).strip()
    parts = [p.strip() for p in city_state.split(",") if p.strip()]
    if parts:
        result["city"] = parts[0]
    if len(parts) > 1:
        # Drop a trailing work-mode word that sometimes rides along with
        # the state ("MA Onsite") without parentheses.
        state = _WORK_MODE_RE.sub("", parts[1]).strip()
        if state:
            result["state"] = state

    return result


def _signature_value(draft: DraftObject, field: str) -> str | None:
    signature = (draft.payload or {}).get("structured_data", {}).get("signature", {})
    field_data = (signature.get("contact") or {}).get(field)
    return field_data.get("value") if isinstance(field_data, dict) else None


def _recruiter_contact(draft: DraftObject) -> dict[str, Any]:
    metadata = draft.metadata or {}
    original = metadata.get("original_sender_candidate") or {}
    sender = metadata.get("sender") or {}

    email = original.get("email") or sender.get("email")
    name = original.get("name") or sender.get("sender_name") or _signature_value(draft, "full_name")
    company = _signature_value(draft, "company")

    return {"email": email, "name": name, "company": company}


def map_draft_to_core_job_payload(draft: DraftObject) -> dict[str, Any]:
    """Builds the CreateParsedJobDto-shaped payload Core's
    POST /hermes/job/create expects. Prefers a recruiter's claim
    corrections (draft.metadata.claimed_fields) over the raw deterministic/
    LLM-fallback parse for every field they could differ on -- a human
    confirmed those, so they outrank anything upstream.
    """
    records: list[dict[str, Any]] = (
        (draft.payload or {}).get("structured_data", {}).get("email_parsing", {}).get("records", [])
    )
    record: dict[str, Any] = records[0] if records else {}
    claimed = (draft.metadata or {}).get("claimed_fields") or {}
    fields = {**record, **claimed}

    required_skills = fields.get("required_skills") or []
    preferred_skills = fields.get("preferred_skills") or []
    all_skills = sorted(set(required_skills) | set(preferred_skills))

    contact = _recruiter_contact(draft)

    payload: dict[str, Any] = {
        "jobTitle": fields.get("job_title") or draft.title or "Untitled Requirement",
        "jobDescription": fields.get("job_description"),
        # The posting's own "End Client:"/"Client:" is who the role is
        # actually for -- that's what belongs on a job listing. The
        # recruiter's own signature company (contact["company"], e.g. a
        # staffing agency) is a fallback only, for postings that never
        # name an end client at all.
        "clientName": fields.get("company") or contact["company"],
        "currency": "USD",
        **_parse_location(fields.get("location")),
        **_parse_rate(fields.get("rate_or_salary")),
    }

    if required_skills:
        payload["primarySkills"] = required_skills
    if all_skills:
        payload["skills"] = all_skills

    employment_type = fields.get("employment_type")
    if employment_type:
        payload["employmentTypes"] = [employment_type]

    work_authorization = fields.get("work_authorization")
    if work_authorization:
        payload["workAuthorizations"] = [work_authorization]

    years = fields.get("years_of_experience")
    if years is not None:
        payload["experienceLevel"] = f"{years}+ years"

    if contact["email"] or contact["name"] or contact["company"]:
        payload["externalSource"] = {
            "sourceType": "EMAIL",
            "recruiterName": contact["name"],
            "recruiterEmail": contact["email"],
            "recruiterCompany": contact["company"],
        }
        payload["recruiterInfo"] = {
            "name": contact["name"],
            "email": contact["email"],
            "companyName": contact["company"],
        }

    return payload


def _record_push_attempt(
    draft_id: str,
    status: str,
    core_job_id: str | None = None,
    core_job_url: str | None = None,
    error: str | None = None,
) -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO core_pushes (draft_id, status, core_job_id, core_job_url, error)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (draft_id, status, core_job_id, core_job_url, error),
        )


def push_job_to_core(draft: DraftObject) -> dict[str, Any]:
    """Never raises. Returns {"status": "pushed"|"skipped"|"failed", ...}.
    Always records the attempt (or the reason it was skipped) to
    core_pushes for visibility -- a silent no-op here would be
    indistinguishable from "hasn't been tried yet."
    """
    if draft.draft_type != "draft_job_requirement":
        return {"status": "skipped", "reason": "not_a_job_requirement"}

    if not core_push_configured():
        _record_push_attempt(draft.draft_id, "failed", error="core_push_not_configured")
        return {"status": "failed", "reason": "core_push_not_configured"}

    payload = map_draft_to_core_job_payload(draft)
    body = json.dumps(payload).encode("utf-8")

    request = Request(
        f"{CORE_API_BASE_URL}/hermes/job/create",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {HERMES_SERVICE_TOKEN}",
            "Content-Type": "application/json",
            # Core sits behind Cloudflare, which blocks the default
            # Python-urllib user agent as bot traffic (WAF error 1010) --
            # confirmed live: identical request succeeds with this header
            # and fails without it. Not a workaround for anything on
            # Core's own auth (HermesAuthGuard) -- that layer is separate
            # and was already passing before this fix.
            "User-Agent": "Hermes-Internal-Service/1.0",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:500]
        error = f"http_{exc.code}: {error_body}"
        _record_push_attempt(draft.draft_id, "failed", error=error)
        return {"status": "failed", "reason": error}
    except (URLError, TimeoutError, ValueError) as exc:
        error = f"request_error: {exc}"
        _record_push_attempt(draft.draft_id, "failed", error=error)
        return {"status": "failed", "reason": error}

    data = result.get("data") or {}
    core_job_id = data.get("job_id") or data.get("id")
    core_job_url = data.get("job_url")
    unmatched = (result.get("extra") or {}).get("unmatchedFields")

    _record_push_attempt(
        draft.draft_id,
        "pushed",
        core_job_id=core_job_id,
        core_job_url=core_job_url,
        error=json.dumps(unmatched) if unmatched else None,
    )

    return {
        "status": "pushed",
        "core_job_id": core_job_id,
        "core_job_url": core_job_url,
        "unmatched_fields": unmatched,
    }
