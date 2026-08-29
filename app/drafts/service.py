import json
from typing import Any
from uuid import uuid4

from psycopg import errors

from app.email_parsing.classification_learning import record_classification_correction
from app.email_parsing.provenance import (
    HOTLIST_CONSULTANT_FIELDS,
    JOB_REQUIREMENT_FIELDS,
    record_reviewer_correction,
)
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


def _title_from_payload(draft_type: DraftObjectType, payload: dict) -> str:
    if draft_type == "draft_job_requirement":
        return payload.get("job_title") or payload.get("title") or "Draft Job Requirement"

    if draft_type in {
        "draft_consultant_profile",
        "draft_recruiter_profile",
        "draft_bench_sales_profile",
    }:
        return payload.get("display_name") or payload.get("name") or "Draft Profile"

    if draft_type == "draft_hotlist":
        return payload.get("name") or "Draft Hotlist"

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


def publish_draft_object(draft_id: str) -> DraftPublishResult:
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
    parsed as a job requirement but is actually a hotlist, or vice versa).
    Updates draft_type in place -- this corrects an existing record, it
    does not create a second draft for the same email.

    When both the original and corrected type are one of the two kinds
    classify_email_by_confidence() actually distinguishes between (hotlist
    vs job requirement), also records the correction for
    app/email_parsing/classification_learning.py to learn from. A
    correction into/out of any other draft type (resume, vendor list,
    etc.) is still applied but not fed into that loop -- the classifier
    it teaches never chooses those.
    """
    draft = get_draft_object(draft_id)
    if not draft:
        return None

    original_draft_type = draft.draft_type

    with cursor() as cur:
        cur.execute(
            "UPDATE drafts SET draft_type = %s, updated_at = now() WHERE draft_id = %s RETURNING *",
            (corrected_draft_type, draft_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    updated = _row_to_draft(row)
    emit_event(
        "draft.reclassified",
        {"draft_id": draft_id, "from": original_draft_type, "to": corrected_draft_type},
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
    """
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
