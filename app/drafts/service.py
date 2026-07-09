from uuid import uuid4

from app.runtime.events import emit_event
from app.runtime.jsonl_store import read_json, runtime_path, write_json

from app.drafts.models import DraftObject, DraftObjectType, DraftPublishResult


_drafts: dict[str, DraftObject] = {}


def _draft_path(draft_id: str):
    return runtime_path("drafts", f"{draft_id}.json")


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
) -> DraftObject:
    draft = DraftObject(
        draft_id=str(uuid4()),
        draft_type=draft_type,
        status="needs_review" if requires_review else "draft",
        source=source,
        source_ref=source_ref,
        channel=channel,
        source_message_id=source_message_id,
        title=_title_from_payload(draft_type, payload),
        summary=payload.get("summary") or payload.get("text") or payload.get("description"),
        payload=payload,
        normalized_skills=normalized_skills or [],
        normalized_job_titles=normalized_job_titles or [],
        taxonomy_signals=taxonomy_signals or {},
        confidence=confidence,
        requires_review=requires_review,
        errors=errors or [],
        metadata=metadata or {},
    )
    _drafts[draft.draft_id] = draft
    write_json(_draft_path(draft.draft_id), draft.model_dump())
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
    if draft_id in _drafts:
        return _drafts[draft_id]

    record = read_json(_draft_path(draft_id))
    if not record:
        return None

    draft = DraftObject(**record)
    _drafts[draft_id] = draft
    return draft


def list_draft_objects() -> list[DraftObject]:
    drafts_dir = runtime_path("drafts", ".keep").parent

    for file_path in drafts_dir.glob("*.json"):
        draft_id = file_path.stem
        if draft_id not in _drafts:
            record = read_json(file_path)
            if record:
                _drafts[draft_id] = DraftObject(**record)

    return list(_drafts.values())


def publish_draft_object(draft_id: str) -> DraftPublishResult:
    draft = get_draft_object(draft_id)

    if not draft:
        return DraftPublishResult(
            status="blocked",
            draft_id=draft_id,
            draft_type="draft_channel_note",
            errors=["draft_not_found"],
        )

    draft.status = "published"
    _drafts[draft.draft_id] = draft
    write_json(_draft_path(draft.draft_id), draft.model_dump())
    emit_event(
        "draft.published",
        {
            "draft_id": draft.draft_id,
            "draft_type": draft.draft_type,
        },
    )

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
