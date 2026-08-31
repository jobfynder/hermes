import json
from typing import Any
from uuid import uuid4

from psycopg import errors

from app.email_parsing.classification_learning import record_classification_correction
from app.email_parsing.llm_fallback import apply_hotlist_fallback, apply_job_requirement_fallback
from app.email_parsing.parsers import parse_email_business_records
from app.email_parsing.provenance import (
    HOTLIST_CONSULTANT_FIELDS,
    JOB_REQUIREMENT_FIELDS,
    record_reviewer_correction,
)
from app.email_parsing.signature_learning import record_signature_correction
from app.integrations.core_job_push import push_job_to_core
from app.runtime.db import cursor
from app.runtime.events import emit_event

from app.drafts.models import DraftObject, DraftObjectType, DraftPublishResult, DraftStatus

# The two draft types classify_email_by_confidence() actually distinguishes
# between (app/email_parsing/parsers.py) -- reclassify_draft_object() only
# feeds the self-learning loop (app/email_parsing/classification_learning.py)
# when a correction moves between these two, since that classifier never
# chooses any of the others.
_LEARNABLE_DRAFT_TYPES: dict[DraftObjectType, str] = {
    "draft_hotlist": "hotlist",
    "draft_job_requirement": "job_description",
}


def _first_email_record_field(payload: dict, field: str) -> Any:
    """The real, deterministic-parser-produced job_title/candidate_name
    lives at payload['structured_data']['email_parsing']['records'][0]
    [field] -- never at payload[field] directly, which is what every
    email-channel draft actually has (see create_draft_object's callers
    in app/channels/service.py: the payload it builds only ever carries
    top-level "text"/"document_kind"/"structured_data", never a bare
    "job_title"). _title_from_payload's own payload.get("job_title")
    check was therefore dead code for every real email draft -- every
    job-requirement title fell straight through to the generic "Draft
    Job Requirement" fallback, which is why the whole review list looked
    identical no matter which posting a row was. Kept payload.get(field)
    as the first check anyway for any future caller that does pass a
    flat payload (e.g. a non-email intake path).
    """
    records = ((payload.get("structured_data") or {}).get("email_parsing") or {}).get("records") or []
    return records[0].get(field) if records else None


def _title_from_payload(draft_type: DraftObjectType, payload: dict) -> str:
    if draft_type == "draft_job_requirement":
        return (
            payload.get("job_title")
            or _first_email_record_field(payload, "job_title")
            or payload.get("title")
            or "Draft Job Requirement"
        )

    if draft_type in {
        "draft_consultant_profile",
        "draft_recruiter_profile",
        "draft_bench_sales_profile",
    }:
        return payload.get("display_name") or payload.get("name") or "Draft Profile"

    if draft_type == "draft_hotlist":
        if payload.get("name"):
            return payload["name"]

        records = ((payload.get("structured_data") or {}).get("email_parsing") or {}).get("records") or []
        if len(records) == 1:
            name = records[0].get("candidate_name")
            if name:
                return name
        elif records:
            return f"Hotlist — {len(records)} consultants"

        return "Draft Hotlist"

    if draft_type == "draft_vendor_list":
        return payload.get("name") or "Draft Vendor List"

    return payload.get("title") or "Draft Channel Note"


def _row_to_draft(row: dict) -> DraftObject:
    return DraftObject(
        draft_id=str(row["draft_id"]),
        draft_type=row["draft_type"],
        status=row["status"],
        source=row["source"],
        source_ref=row["source_ref"],
        channel=row["channel"],
        source_message_id=row["source_message_id"],
        title=row["title"],
        summary=row["summary"],
        payload=row["payload"],
        normalized_skills=row["normalized_skills"],
        normalized_job_titles=row["normalized_job_titles"],
        taxonomy_signals=row["taxonomy_signals"],
        confidence=row["confidence"],
        requires_review=row["requires_review"],
        errors=row["errors"],
        metadata=row["metadata"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
    )


def create_draft_object(
    draft_type: DraftObjectType,
    source: str,
    payload: dict,
    source_ref: str | None = None,
    channel: str | None = None,
    source_message_id: str | None = None,
    normalized_skills: list[str] | None = None,
    normalized_job_titles: list[str] | None = None,
    taxonomy_signals: dict | None = None,
    confidence: float = 0.0,
    requires_review: bool = True,
    errors: list[str] | None = None,
    metadata: dict | None = None,
    status_override: DraftStatus | None = None,
) -> DraftObject:
    draft_id = str(uuid4())
    # status_override exists for exactly one caller today: intake flagging
    # a message as likely spam (app/email_parsing/spam.py) still creates a
    # normal, reviewable draft -- just stamped "spam" from the start
    # instead of the usual draft/needs_review -- rather than the silent
    # blocklist path, which never reaches create_draft_object at all.
    status = status_override or ("needs_review" if requires_review else "draft")
    title = _title_from_payload(draft_type, payload)
    summary = payload.get("summary") or payload.get("text") or payload.get("description")

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO drafts (
                draft_id, draft_type, status, source, source_ref, channel,
                source_message_id, title, summary, payload, normalized_skills,
                normalized_job_titles, taxonomy_signals, confidence,
                requires_review, errors, metadata
            ) VALUES (
                %(draft_id)s, %(draft_type)s, %(status)s, %(source)s, %(source_ref)s,
                %(channel)s, %(source_message_id)s, %(title)s, %(summary)s,
                %(payload)s, %(normalized_skills)s, %(normalized_job_titles)s,
                %(taxonomy_signals)s, %(confidence)s, %(requires_review)s,
                %(errors)s, %(metadata)s
            )
            """,
            {
                "draft_id": draft_id,
                "draft_type": draft_type,
                "status": status,
                "source": source,
                "source_ref": source_ref,
                "channel": channel,
                "source_message_id": source_message_id,
                "title": title,
                "summary": summary,
                "payload": json.dumps(payload, default=str),
                "normalized_skills": json.dumps(normalized_skills or [], default=str),
                "normalized_job_titles": json.dumps(normalized_job_titles or [], default=str),
                "taxonomy_signals": json.dumps(taxonomy_signals or {}, default=str),
                "confidence": confidence,
                "requires_review": requires_review,
                "errors": json.dumps(errors or [], default=str),
                "metadata": json.dumps(metadata or {}, default=str),
            },
        )

    draft = DraftObject(
        draft_id=draft_id,
        draft_type=draft_type,
        status=status,
        source=source,
        source_ref=source_ref,
        channel=channel,
        source_message_id=source_message_id,
        title=title,
        summary=summary,
        payload=payload,
        normalized_skills=normalized_skills or [],
        normalized_job_titles=normalized_job_titles or [],
        taxonomy_signals=taxonomy_signals or {},
        confidence=confidence,
        requires_review=requires_review,
        errors=errors or [],
        metadata=metadata or {},
    )
    emit_event(
        "draft.created",
        {
            "draft_id": draft.draft_id,
            "draft_type": draft.draft_type,
            "source": draft.source,
            "channel": draft.channel,
            "source_message_id": draft.source_message_id,
        },
    )
    return draft


def get_draft_object(draft_id: str) -> DraftObject | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM drafts WHERE draft_id = %s", (draft_id,))
        row = cur.fetchone()

    return _row_to_draft(row) if row else None


def list_draft_objects() -> list[DraftObject]:
    with cursor() as cur:
        cur.execute("SELECT * FROM drafts ORDER BY created_at DESC")
        rows = cur.fetchall()

    return [_row_to_draft(row) for row in rows]


def _draft_summary_title(row: dict) -> str:
    """Mirrors the frontend's draftDisplayTitle() (app/components/
    DraftTypeLabel.tsx) so the list page shows the same title either way
    -- computed here in SQL/Python instead so the list endpoint never has
    to pull the full payload just to read one or two fields out of it.
    """
    if row["draft_type"] == "draft_job_requirement" and row.get("record_job_title"):
        return row["record_job_title"]

    if row["draft_type"] == "draft_hotlist":
        record_count = row.get("record_count") or 0
        if record_count == 1 and row.get("record_candidate_name"):
            return row["record_candidate_name"]
        if record_count > 1:
            return f"Hotlist — {record_count} consultants"

    return row.get("title") or "(untitled)"


def list_draft_summaries() -> list[dict]:
    """What the drafts list page actually renders per row -- type,
    status, confidence, sender, and a title -- without ever pulling the
    full `payload` column (raw email text, complete parsed records,
    provenance-sized JSON; averages several KB per draft). Once the
    drafts table passed a thousand rows this was the single biggest cost
    in loading the review page, and almost none of that data was ever
    displayed in the list. Only the two JSON paths the title needs are
    extracted, straight in SQL, instead of shipping the whole payload
    to Python (and then to the browser) just to read one field out of it.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                draft_id, draft_type, status, confidence, created_at, metadata,
                source_message_id, title,
                payload->'structured_data'->'email_parsing'->'records'->0->>'job_title'
                    AS record_job_title,
                payload->'structured_data'->'email_parsing'->'records'->0->>'candidate_name'
                    AS record_candidate_name,
                jsonb_array_length(
                    COALESCE(payload->'structured_data'->'email_parsing'->'records', '[]'::jsonb)
                ) AS record_count
            FROM drafts
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()

    return [
        {
            "draft_id": str(row["draft_id"]),
            "draft_type": row["draft_type"],
            "status": row["status"],
            "confidence": row["confidence"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "metadata": row["metadata"],
            "source_message_id": row["source_message_id"],
            "display_title": _draft_summary_title(row),
        }
        for row in rows
    ]


def update_draft_metadata(draft_id: str, extra_metadata: dict) -> DraftObject | None:
    """Merge additional keys into a draft's metadata without touching its
    status. Used by the claim-and-verify loop (app/claim/service.py) to
    attach a recruiter's corrected fields onto the draft before it is
    published, so the published record reflects what the recruiter
    actually confirmed rather than the raw parse.
    """
    with cursor() as cur:
        cur.execute(
            """
            UPDATE drafts
            SET metadata = metadata || %(extra)s::jsonb, updated_at = now()
            WHERE draft_id = %(draft_id)s
            RETURNING *
            """,
            {"draft_id": draft_id, "extra": json.dumps(extra_metadata, default=str)},
        )
        row = cur.fetchone()

    return _row_to_draft(row) if row else None


def _publish_block_reason(draft: DraftObject) -> str | None:
    """A hard stop before a job requirement reaches Jobfynder Core: Hermes
    is the staging layer in front of the live site now, so a draft still
    flagged requires_review with no job title would otherwise go live as
    a blank/broken posting. Deliberately narrow -- a reviewer can still
    publish any other requires_review draft they've actually looked at
    (corrections don't clear the flag, see apply_field_corrections), this
    only catches the "never opened it, still missing the one field a live
    posting can't do without" case.
    """
    if draft.draft_type != "draft_job_requirement" or not draft.requires_review:
        return None

    records = ((draft.payload.get("structured_data") or {}).get("email_parsing") or {}).get("records") or []
    if not records:
        return "job_requirement_missing_records"

    if not (records[0].get("job_title") or "").strip():
        return "job_requirement_missing_job_title"

    return None


def publish_draft_object(draft_id: str) -> DraftPublishResult:
    existing = get_draft_object(draft_id)
    if not existing:
        return DraftPublishResult(
            status="blocked",
            draft_id=draft_id,
            draft_type="draft_channel_note",
            errors=["draft_not_found"],
        )

    block_reason = _publish_block_reason(existing)
    if block_reason:
        return DraftPublishResult(
            status="blocked",
            draft_id=existing.draft_id,
            draft_type=existing.draft_type,
            errors=[block_reason],
        )

    with cursor() as cur:
        cur.execute(
            "UPDATE drafts SET status = 'published', updated_at = now() "
            "WHERE draft_id = %s RETURNING *",
            (draft_id,),
        )
        row = cur.fetchone()

    if not row:
        return DraftPublishResult(
            status="blocked",
            draft_id=draft_id,
            draft_type="draft_channel_note",
            errors=["draft_not_found"],
        )

    draft = _row_to_draft(row)
    emit_event("draft.published", {"draft_id": draft.draft_id, "draft_type": draft.draft_type})

    # Last step of the pipeline: only a PUBLISHED job-requirement draft
    # ever reaches Jobfynder Core, and even then it lands as DRAFT there
    # too (Core's own separate publish step still gates going live) --
    # see app/integrations/core_job_push.py for the full boundary
    # rationale. Never allowed to fail this function: a push failure is
    # recorded for retry/follow-up, not surfaced as a failed publish --
    # the draft *is* published in Hermes regardless of whether Core's
    # side could be reached just now.
    push_result = push_job_to_core(draft)
    if push_result["status"] != "skipped":
        update_draft_metadata(draft.draft_id, {"core_push": push_result})

    return DraftPublishResult(
        status="published",
        draft_id=draft.draft_id,
        draft_type=draft.draft_type,
        published_payload={
            "draft_id": draft.draft_id,
            "draft_type": draft.draft_type,
            "payload": draft.payload,
            "normalized_skills": draft.normalized_skills,
            "normalized_job_titles": draft.normalized_job_titles,
        },
        errors=[],
    )


def reject_draft_object(draft_id: str, reason: str | None = None) -> DraftPublishResult:
    """The reviewer decided a draft shouldn't become a real record (e.g. a
    hotlist/profile draft with no Core-side auto-creation path, or a
    requirement draft judged not worth acting on). Mirrors
    publish_draft_object's shape/behavior -- sets a terminal status so the
    draft stops showing up as pending review, but never deletes the
    record, keeping it available for audit.
    """
    extra_metadata = {"rejection_reason": reason} if reason else {}

    with cursor() as cur:
        cur.execute(
            """
            UPDATE drafts
            SET status = 'rejected', metadata = metadata || %(extra)s::jsonb, updated_at = now()
            WHERE draft_id = %(draft_id)s
            RETURNING *
            """,
            {"draft_id": draft_id, "extra": json.dumps(extra_metadata, default=str)},
        )
        row = cur.fetchone()

    if not row:
        return DraftPublishResult(
            status="blocked",
            draft_id=draft_id,
            draft_type="draft_channel_note",
            errors=["draft_not_found"],
        )

    draft = _row_to_draft(row)
    emit_event(
        "draft.rejected",
        {"draft_id": draft.draft_id, "draft_type": draft.draft_type, "reason": reason},
    )

    return DraftPublishResult(status="rejected", draft_id=draft.draft_id, draft_type=draft.draft_type, errors=[])


def reclassify_draft_object(draft_id: str, corrected_draft_type: DraftObjectType) -> DraftObject | None:
    """A reviewer determined this draft's document kind was wrong (e.g.
    parsed as a resume but is actually a job requirement, or hotlist vs.
    requirement). Updates draft_type in place -- this corrects an
    existing record, it does not create a second draft for the same
    email.

    Critical, and not obvious from the name: flipping draft_type alone
    used to leave structured_data.email_parsing exactly as it was under
    the WRONG original classification -- which for a job_requirement/
    hotlist correction almost always means an empty records[] (parse_
    email_business_records refuses to extract job/hotlist fields from a
    document_kind it wasn't given, see its own "unsupported_email_
    document_kind" warning). The draft would show the corrected type in
    the list, but have nothing a reviewer could actually publish.
    Confirmed against a real production draft: an email correctly
    misclassified as a resume, reclassified to draft_job_requirement by
    a reviewer, ended up with zero parsed fields and a stale "Draft
    Profile" title. Fixed here by actually re-running the deterministic
    parser (+ LLM fallback, same as real intake) against the draft's own
    stored text under the corrected document_kind, whenever the
    correction target is one of the two kinds that has one --
    reclassifying into/out of a profile/vendor-list/channel-note type
    has no equivalent business parser and is still just a label flip.

    Separately: when both the original and corrected type are one of the
    two kinds classify_email_by_confidence() actually distinguishes
    between (hotlist vs job requirement), also records the correction
    for app/email_parsing/classification_learning.py to learn from.
    """
    draft = get_draft_object(draft_id)
    if not draft:
        return None

    original_draft_type = draft.draft_type
    reparse_target = _LEARNABLE_DRAFT_TYPES.get(corrected_draft_type)

    payload = draft.payload
    confidence = draft.confidence
    requires_review = draft.requires_review
    title = draft.title

    if reparse_target and draft.channel == "email":
        text = payload.get("text") or ""
        email_parsing = parse_email_business_records(text=text, document_kind=reparse_target)

        if reparse_target == "job_description":
            email_parsing, _ = apply_job_requirement_fallback(text, email_parsing)
        elif reparse_target == "hotlist":
            email_parsing, _ = apply_hotlist_fallback(text, email_parsing)

        structured_data = payload.get("structured_data") or {}
        structured_data["email_parsing"] = email_parsing
        structured_data["document_kind"] = reparse_target
        payload = {**payload, "structured_data": structured_data, "document_kind": reparse_target}

        confidence = float(email_parsing.get("confidence", confidence))
        requires_review = bool(email_parsing.get("requires_review", True))
        title = _title_from_payload(corrected_draft_type, payload)

    with cursor() as cur:
        cur.execute(
            "UPDATE drafts SET draft_type = %s, payload = %s, confidence = %s, "
            "requires_review = %s, title = %s, updated_at = now() WHERE draft_id = %s RETURNING *",
            (
                corrected_draft_type,
                json.dumps(payload, default=str),
                confidence,
                requires_review,
                title,
                draft_id,
            ),
        )
        row = cur.fetchone()

    if not row:
        return None

    updated = _row_to_draft(row)
    emit_event(
        "draft.reclassified",
        {
            "draft_id": draft_id,
            "from": original_draft_type,
            "to": corrected_draft_type,
            "reparsed": bool(reparse_target and draft.channel == "email"),
        },
    )

    if original_draft_type in _LEARNABLE_DRAFT_TYPES and corrected_draft_type in _LEARNABLE_DRAFT_TYPES:
        sender = (updated.metadata or {}).get("sender") or {}
        record_classification_correction(
            draft_id=draft_id,
            sender_email=sender.get("email"),
            predicted_document_kind=_LEARNABLE_DRAFT_TYPES[original_draft_type],
            corrected_document_kind=_LEARNABLE_DRAFT_TYPES[corrected_draft_type],
            predicted_confidence=updated.confidence,
        )

    return updated


def delete_draft_object(draft_id: str) -> dict:
    """Hard-deletes a draft row -- the one genuinely destructive action in
    this module, unlike reject/publish which only flip status and keep the
    record for audit. Exists specifically for the spam-review workflow
    (HERMES-900): a human looked at a draft flagged status='spam' and
    confirmed it, so there is nothing worth auditing. Deliberately refuses
    to delete a published draft (it may already be live on Jobfynder Core,
    referenced by core_pushes) -- reject it first if it truly needs to go
    away. email_claims/core_pushes both carry a plain FK with no cascade,
    so any other still-referenced draft fails loudly via IntegrityError
    rather than leaving an orphaned claim/push row.
    """
    draft = get_draft_object(draft_id)
    if not draft:
        return {"deleted": False, "reason": "draft_not_found"}

    if draft.status == "published":
        return {"deleted": False, "reason": "cannot_delete_published_draft"}

    try:
        with cursor() as cur:
            cur.execute("DELETE FROM drafts WHERE draft_id = %s", (draft_id,))
            deleted = cur.rowcount > 0
    except errors.ForeignKeyViolation:
        return {"deleted": False, "reason": "draft_has_related_claim_or_core_push"}

    if deleted:
        emit_event(
            "draft.deleted",
            {"draft_id": draft_id, "draft_type": draft.draft_type, "status_before_delete": draft.status},
        )

    return {"deleted": deleted}


# Which of each record type's fields a reviewer is allowed to hand-edit on
# the review page. job_description is deliberately excluded -- it's a
# free-text block shown in its own collapsible section, not a labeled
# field row, and editing prose isn't what this correction-tracking loop
# is for.
_EDITABLE_FIELDS: dict[str, set[str]] = {
    "job_requirement": set(JOB_REQUIREMENT_FIELDS) - {"job_description"},
    "hotlist": set(HOTLIST_CONSULTANT_FIELDS),
}


def apply_field_corrections(
    draft_id: str,
    record_type: str,
    record_index: int,
    corrections: dict[str, Any],
) -> DraftObject | None:
    """Lets a reviewer fix one or more fields on the review page instead
    of the only two prior options -- publish a draft with a field known
    to be wrong, or reject the whole thing and lose everything else that
    parsed correctly. Every actual change is also recorded via
    record_reviewer_correction (app/email_parsing/provenance.py) as a
    field_provenance row -- the same accuracy-labeling signal claim-flow
    corrections already produce, and what app/drafts/accuracy.py reads
    to compute per-field precision. Silently drops any key in
    `corrections` that isn't in _EDITABLE_FIELDS for this record_type,
    rather than raising, so a client sending an unexpected extra key
    doesn't fail the whole request.

    record_type="signature" is handled separately by
    _apply_signature_corrections -- the signature block isn't a fixed
    schema like job_requirement/hotlist (see app/email_parsing/
    signature.py), so "allowed" there is whatever fields this specific
    draft's signature actually detected, not a static set.
    """
    if record_type == "signature":
        return _apply_signature_corrections(draft_id, corrections)

    if record_type not in _EDITABLE_FIELDS:
        raise ValueError(f"unsupported record_type {record_type!r}")

    allowed = _EDITABLE_FIELDS[record_type]
    corrections = {field: value for field, value in corrections.items() if field in allowed}

    draft = get_draft_object(draft_id)
    if not draft:
        return None

    if not corrections:
        return draft

    email_parsing = (draft.payload.get("structured_data") or {}).get("email_parsing") or {}
    records = email_parsing.get("records") or []

    if not (0 <= record_index < len(records)):
        raise ValueError(f"record_index {record_index} out of range (draft has {len(records)} records)")

    record = records[record_index]

    if record_type == "job_requirement":
        field_prefix = "job."
    else:
        # Must match build_hotlist_provenance's own ordinal exactly
        # (app/email_parsing/provenance.py) -- that's the field_path a
        # correction here needs to line up with, both so the review
        # page's provenance chip for this specific consultant stays
        # correctly matched, and so the accuracy rollup (which strips the
        # ordinal and groups by field name) sees the correction and the
        # original extraction as the same field.
        ordinal = record.get("source_row") or record.get("source_block") or 0
        field_prefix = f"consultant.{ordinal}."

    changed_fields: list[str] = []

    for field, new_value in corrections.items():
        old_value = record.get(field)
        if new_value == old_value:
            continue
        record[field] = new_value
        changed_fields.append(field)
        record_reviewer_correction(
            parse_run_id=draft_id,
            field_path=f"{field_prefix}{field}",
            before=old_value,
            after=new_value,
        )

    if not changed_fields:
        return draft

    with cursor() as cur:
        cur.execute(
            "UPDATE drafts SET payload = %s, updated_at = now() WHERE draft_id = %s RETURNING *",
            (json.dumps(draft.payload, default=str), draft_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    emit_event(
        "draft.field_corrected",
        {
            "draft_id": draft_id,
            "record_type": record_type,
            "record_index": record_index,
            "changed_fields": changed_fields,
        },
    )

    return _row_to_draft(row)


def _apply_signature_corrections(draft_id: str, corrections: dict[str, Any]) -> DraftObject | None:
    """Corrects sender-signature fields (name/email/company/title, etc. --
    deterministically extracted from the email's own signature block, see
    app/email_parsing/signature.py) the same way apply_field_corrections
    does for job_requirement/hotlist fields, plus one more step: also
    remembers the correction per sender domain (signature_corrections
    table) so the next email from that domain gets the gap filled in
    automatically instead of a reviewer fixing the same field forever --
    see app/email_parsing/signature_learning.py.
    """
    draft = get_draft_object(draft_id)
    if not draft:
        return None

    structured_data = draft.payload.get("structured_data") or {}
    signature = structured_data.get("signature") or {}
    contact = signature.get("contact") or {}

    # Only a field the parser actually detected for this draft is
    # editable -- no injecting brand-new keys the signature parser
    # doesn't produce.
    corrections = {field: value for field, value in corrections.items() if field in contact}
    if not corrections:
        return draft

    sender_email = (draft.metadata or {}).get("sender", {}).get("email") or ""
    sender_domain = sender_email.rsplit("@", 1)[-1].lower() if "@" in sender_email else None

    changed_fields: list[str] = []

    for field, new_value in corrections.items():
        old_value = contact[field].get("value")
        if new_value == old_value:
            continue

        contact[field] = {**contact[field], "value": new_value, "method": "human_edited", "confidence": 1.0}
        changed_fields.append(field)

        record_reviewer_correction(
            parse_run_id=draft_id,
            field_path=f"signature.{field}",
            before=old_value,
            after=new_value,
        )

        if sender_domain and isinstance(new_value, str) and new_value.strip():
            record_signature_correction(sender_domain, field, new_value.strip())

    if not changed_fields:
        return draft

    with cursor() as cur:
        cur.execute(
            "UPDATE drafts SET payload = %s, updated_at = now() WHERE draft_id = %s RETURNING *",
            (json.dumps(draft.payload, default=str), draft_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    emit_event(
        "draft.field_corrected",
        {"draft_id": draft_id, "record_type": "signature", "record_index": 0, "changed_fields": changed_fields},
    )

    return _row_to_draft(row)
