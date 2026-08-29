import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.claim.models import ClaimConfirmResult, ClaimPrepareResult, EmailClaim
from app.drafts.service import get_draft_object, publish_draft_object, update_draft_metadata
from app.email_parsing.provenance import JOB_REQUIREMENT_FIELDS, record_recruiter_correction
from app.email_parsing.sender_resolver import find_body_contact_email
from app.runtime.db import cursor
from app.runtime.events import emit_event


CLAIM_EXPIRY_DAYS = 14


def _row_to_claim(row: dict) -> EmailClaim:
    return EmailClaim(
        claim_id=str(row["claim_id"]),
        draft_id=str(row["draft_id"]),
        token=row["token"],
        status=row["status"],
        recruiter_email=row["recruiter_email"],
        recruiter_name=row["recruiter_name"],
        resolution_method=row["resolution_method"],
        resolution_confidence=row["resolution_confidence"],
        prefilled_fields=row["prefilled_fields"],
        correction_diff=row["correction_diff"],
        created_at=row["created_at"].isoformat(),
        sent_at=row["sent_at"].isoformat() if row["sent_at"] else None,
        claimed_at=row["claimed_at"].isoformat() if row["claimed_at"] else None,
        published_at=row["published_at"].isoformat() if row["published_at"] else None,
        expires_at=row["expires_at"].isoformat(),
    )


def _save_claim(claim: EmailClaim) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE email_claims SET
                status = %(status)s,
                correction_diff = %(correction_diff)s,
                sent_at = %(sent_at)s,
                claimed_at = %(claimed_at)s,
                published_at = %(published_at)s,
                expires_at = %(expires_at)s
            WHERE claim_id = %(claim_id)s
            """,
            {
                "claim_id": claim.claim_id,
                "status": claim.status,
                "correction_diff": json.dumps(claim.correction_diff, default=str) if claim.correction_diff is not None else None,
                "sent_at": claim.sent_at,
                "claimed_at": claim.claimed_at,
                "published_at": claim.published_at,
                "expires_at": claim.expires_at,
            },
        )


def get_claim(claim_id: str) -> EmailClaim | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM email_claims WHERE claim_id = %s", (claim_id,))
        row = cur.fetchone()

    return _row_to_claim(row) if row else None


def get_claim_by_token(token: str) -> EmailClaim | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM email_claims WHERE token = %s", (token,))
        row = cur.fetchone()

    return _row_to_claim(row) if row else None


def get_claim_by_draft(draft_id: str) -> EmailClaim | None:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM email_claims WHERE draft_id = %s ORDER BY created_at DESC LIMIT 1",
            (draft_id,),
        )
        row = cur.fetchone()

    return _row_to_claim(row) if row else None


def is_expired(claim: EmailClaim) -> bool:
    if claim.status != "PENDING_CLAIM":
        return False
    return datetime.now(UTC) > datetime.fromisoformat(claim.expires_at)


def _resolve_recruiter_contact(draft) -> tuple[str, str | None, str, float] | None:
    """Recruiter contact resolution precedence for the claim step (spec
    4.1/11.1): a resolved forwarded-mail sender first, then the direct
    envelope sender, then a contact email found in the body itself. Returns
    None -- never guesses -- when nothing resolves, matching sender_resolver's
    own "do not guess" rule.
    """
    metadata = draft.metadata or {}

    original = metadata.get("original_sender_candidate")
    if original and original.get("email"):
        return (
            original["email"],
            original.get("name"),
            original["extraction_method"],
            float(original.get("confidence") or 0.0),
        )

    sender = metadata.get("sender")
    if sender and sender.get("email"):
        return (sender["email"], sender.get("sender_name"), "direct_sender", 0.99)

    body_email = find_body_contact_email((draft.payload or {}).get("text", ""))
    if body_email:
        return (body_email, None, "body_contact", 0.5)

    return None


def _first_job_record(draft) -> dict[str, Any]:
    email_parsing = (draft.payload or {}).get("structured_data", {}).get("email_parsing", {})
    records = email_parsing.get("records") or []
    return records[0] if records else {}


def _prefilled_fields_from_draft(draft) -> dict[str, Any]:
    record = _first_job_record(draft)
    return {field: record.get(field) for field in JOB_REQUIREMENT_FIELDS}


def build_claim_email_content(claim: EmailClaim, draft) -> tuple[str, str]:
    """Deterministic claim-email template (spec section 11.1). Hermes
    prepares the content; it never sends it -- Core/n8n owns outbound
    delivery (see app/providers/email/service.py: supports_outbound is
    False by design, per the Hermes/COMM responsibility boundary).
    """
    fields = claim.prefilled_fields
    title = fields.get("job_title") or "your job requirement"

    subject = f"Your job posting is ready to publish on Jobfynder: {title}"

    greeting = f"Hi{' ' + claim.recruiter_name if claim.recruiter_name else ''},"
    skills = ", ".join(fields.get("required_skills") or []) or "(not detected)"

    lines = [
        greeting,
        "",
        "We've already filled in your job posting on Jobfynder from the email you sent:",
        "",
        f"  Title: {fields.get('job_title') or '(not detected)'}",
        f"  Location: {fields.get('location') or '(not detected)'}",
        f"  Rate/Salary: {fields.get('rate_or_salary') or '(not detected)'}",
        f"  Employment type: {fields.get('employment_type') or '(not detected)'}",
        f"  Work authorization: {fields.get('work_authorization') or '(not detected)'}",
        f"  Required skills: {skills}",
        "",
        f"Review and publish here: /claim/{claim.token}",
        "",
        f"This link expires in {CLAIM_EXPIRY_DAYS} days. If you don't confirm, the posting "
        "stays unpublished -- nothing goes live without your say-so.",
    ]

    return subject, "\n".join(lines)


def prepare_claim(draft_id: str) -> ClaimPrepareResult:
    draft = get_draft_object(draft_id)

    if not draft:
        return ClaimPrepareResult(status="blocked", errors=["draft_not_found"])

    if draft.channel != "email" or draft.draft_type != "draft_job_requirement":
        return ClaimPrepareResult(status="blocked", errors=["not_eligible_for_claim"])

    existing = get_claim_by_draft(draft_id)
    if existing:
        subject, body = build_claim_email_content(existing, draft)
        return ClaimPrepareResult(
            status="already_prepared",
            claim=existing,
            email_subject=subject,
            email_body=body,
            claim_url_path=f"/claim/{existing.token}",
        )

    contact = _resolve_recruiter_contact(draft)
    if contact is None:
        # spec 4.1 step 4 / 11.1 point 7: no resolved contact means no
        # claim email sends. The draft stays exactly where it is --
        # visible for manual review, not silently dropped.
        return ClaimPrepareResult(status="blocked", errors=["no_recruiter_contact_resolved"])

    email, name, method, confidence = contact
    now = datetime.now(UTC)

    claim = EmailClaim(
        claim_id=str(uuid4()),
        draft_id=draft_id,
        token=secrets.token_urlsafe(32),
        status="PENDING_CLAIM",
        recruiter_email=email,
        recruiter_name=name,
        resolution_method=method,
        resolution_confidence=confidence,
        prefilled_fields=_prefilled_fields_from_draft(draft),
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=CLAIM_EXPIRY_DAYS)).isoformat(),
    )

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_claims (
                claim_id, draft_id, token, status, recruiter_email, recruiter_name,
                resolution_method, resolution_confidence, prefilled_fields, expires_at
            ) VALUES (
                %(claim_id)s, %(draft_id)s, %(token)s, %(status)s, %(recruiter_email)s,
                %(recruiter_name)s, %(resolution_method)s, %(resolution_confidence)s,
                %(prefilled_fields)s, %(expires_at)s
            )
            """,
            {
                "claim_id": claim.claim_id,
                "draft_id": claim.draft_id,
                "token": claim.token,
                "status": claim.status,
                "recruiter_email": claim.recruiter_email,
                "recruiter_name": claim.recruiter_name,
                "resolution_method": claim.resolution_method,
                "resolution_confidence": claim.resolution_confidence,
                "prefilled_fields": json.dumps(claim.prefilled_fields, default=str),
                "expires_at": claim.expires_at,
            },
        )

    emit_event(
        "claim.prepared",
        {
            "claim_id": claim.claim_id,
            "draft_id": draft_id,
            "resolution_method": method,
            "resolution_confidence": confidence,
        },
    )

    subject, body = build_claim_email_content(claim, draft)
    return ClaimPrepareResult(
        status="prepared",
        claim=claim,
        email_subject=subject,
        email_body=body,
        claim_url_path=f"/claim/{claim.token}",
    )


def mark_claim_sent(claim_id: str) -> EmailClaim | None:
    claim = get_claim(claim_id)
    if not claim:
        return None

    claim.sent_at = datetime.now(UTC).isoformat()
    _save_claim(claim)
    emit_event("claim.sent", {"claim_id": claim_id})
    return claim


def confirm_claim(token: str, corrections: dict[str, Any] | None = None) -> ClaimConfirmResult:
    claim = get_claim_by_token(token)

    if not claim:
        return ClaimConfirmResult(status="blocked", errors=["claim_not_found"])

    if claim.status in ("CLAIMED", "PUBLISHED"):
        # Idempotent re-confirm (e.g. a doubled click) returns the existing
        # outcome rather than reprocessing corrections a second time.
        return ClaimConfirmResult(status="claimed", claim=claim, correction_diff=claim.correction_diff or {})

    if claim.status == "EXPIRED" or is_expired(claim):
        claim.status = "EXPIRED"
        _save_claim(claim)
        return ClaimConfirmResult(status="blocked", claim=claim, errors=["claim_expired"])

    corrections = corrections or {}
    diff: dict[str, Any] = {}

    for field, new_value in corrections.items():
        if field not in JOB_REQUIREMENT_FIELDS:
            continue

        old_value = claim.prefilled_fields.get(field)
        if new_value != old_value:
            diff[field] = {"before": old_value, "after": new_value}
            record_recruiter_correction(
                parse_run_id=claim.draft_id,
                field_path=f"job.{field}",
                before=old_value,
                after=new_value,
            )

    merged_fields = {**claim.prefilled_fields, **corrections}

    claim.correction_diff = diff
    claim.claimed_at = datetime.now(UTC).isoformat()
    claim.status = "CLAIMED"
    _save_claim(claim)

    emit_event(
        "claim.claimed",
        {"claim_id": claim.claim_id, "draft_id": claim.draft_id, "correction_count": len(diff)},
    )

    update_draft_metadata(claim.draft_id, {"claimed_fields": merged_fields, "claim_id": claim.claim_id})
    publish_draft_object(claim.draft_id)

    claim.status = "PUBLISHED"
    claim.published_at = datetime.now(UTC).isoformat()
    _save_claim(claim)

    emit_event("claim.published", {"claim_id": claim.claim_id, "draft_id": claim.draft_id})

    return ClaimConfirmResult(status="claimed", claim=claim, correction_diff=diff)
