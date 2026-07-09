from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse, DocumentKind
from app.drafts.service import create_draft_object
from app.runtime.events import emit_event
from app.runtime.intake_log import (
    load_idempotency_keys,
    record_idempotency_key,
    record_intake,
)
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


_seen_duplicate_keys: set[str] = load_idempotency_keys()


def build_duplicate_key(request: ChannelIntakeRequest) -> str:
    return f"{request.channel}:{request.source_message_id}"


def detect_document_kind(request: ChannelIntakeRequest) -> DocumentKind:
    text = (request.text or "").lower()

    if not text and request.attachments:
        return "unknown"

    resume_markers = [
        "resume",
        "curriculum vitae",
        "professional summary",
        "work experience",
        "education",
    ]
    jd_markers = [
        "job description",
        "required skills",
        "responsibilities",
        "requirements",
        "rate",
        "location",
    ]
    hotlist_markers = [
        "hotlist",
        "available consultants",
        "bench list",
    ]
    vendor_markers = [
        "vendor list",
        "implementation partner",
        "prime vendor",
    ]

    if any(marker in text for marker in hotlist_markers):
        return "hotlist"
    if any(marker in text for marker in vendor_markers):
        return "vendor_list"
    if any(marker in text for marker in jd_markers):
        return "job_description"
    if any(marker in text for marker in resume_markers):
        return "resume"
    if "bench sales" in text:
        return "bench_sales_profile"
    if "recruiter" in text:
        return "recruiter_profile"

    return "plain_message" if text.strip() else "unknown"


def draft_object_for(document_kind: DocumentKind) -> str:
    mapping = {
        "resume": "draft_consultant_profile",
        "job_description": "draft_job_requirement",
        "hotlist": "draft_hotlist",
        "recruiter_profile": "draft_recruiter_profile",
        "bench_sales_profile": "draft_bench_sales_profile",
        "consultant_profile": "draft_consultant_profile",
        "vendor_list": "draft_vendor_list",
        "plain_message": "draft_channel_note",
        "unknown": "draft_channel_note",
    }
    return mapping[document_kind]


def confidence_from_understanding(result: dict, document_kind: DocumentKind) -> float:
    quality = result.get("quality", {})
    score = quality.get("confidence")

    if isinstance(score, int | float):
        return float(score)

    if document_kind == "unknown":
        return 0.2
    if document_kind == "plain_message":
        return 0.6
    return 0.75


def process_channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    duplicate_key = build_duplicate_key(request)

    if duplicate_key in _seen_duplicate_keys:
        record_intake(
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "status": "duplicate",
                "document_kind": "unknown",
            }
        )
        emit_event(
            "intake.duplicate",
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
            },
        )
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="duplicate",
            document_kind="unknown",
            requires_review=True,
            confidence=0.0,
            errors=["duplicate_message"],
            duplicate_key=duplicate_key,
        )

    _seen_duplicate_keys.add(duplicate_key)
    record_idempotency_key(duplicate_key)
    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "received",
            "content_type": request.content_type,
            "has_text": bool(request.text),
            "attachment_count": len(request.attachments),
        }
    )
    emit_event(
        "intake.received",
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
        },
    )

    document_kind = detect_document_kind(request)

    if not request.text and not request.attachments:
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="failed",
            document_kind=document_kind,
            draft_object_type=draft_object_for(document_kind),
            requires_review=True,
            confidence=0.0,
            errors=["empty_intake"],
            duplicate_key=duplicate_key,
        )

    understanding = understand_document(
        RawDocument(
            content=request.text or "",
            filename=None,
            content_type="text/plain",
            document_kind=document_kind,
        )
    )

    understanding_dict = understanding.model_dump()
    structured_data = understanding_dict.get("structured_data", {})
    taxonomy_signals = structured_data.get("taxonomy_signals", {})

    normalized_skills = structured_data.get("normalized_skills", [])
    normalized_job_titles = structured_data.get("normalized_job_titles", [])

    confidence = confidence_from_understanding(
        result=understanding_dict,
        document_kind=document_kind,
    )

    requires_review = confidence < 0.7 or document_kind in {"unknown", "plain_message"}

    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "parsed",
            "document_kind": document_kind,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
            "confidence": confidence,
            "requires_review": requires_review,
        }
    )
    emit_event(
        "intake.parsed",
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "document_kind": document_kind,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
        },
    )

    draft_type = draft_object_for(document_kind)

    draft = create_draft_object(
        draft_type=draft_type,
        source="channel_text_intake",
        source_ref=duplicate_key,
        channel=request.channel,
        source_message_id=request.source_message_id,
        payload={
            "text": request.text or "",
            "document_kind": document_kind,
            "structured_data": structured_data,
        },
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        taxonomy_signals=taxonomy_signals,
        confidence=confidence,
        requires_review=requires_review,
        metadata={
            "duplicate_key": duplicate_key,
            "content_type": request.content_type,
        },
    )

    return ChannelIntakeResponse(
        channel=request.channel,
        source_message_id=request.source_message_id,
        intake_status="parsed",
        document_kind=document_kind,
        understanding_result={
            **understanding_dict,
            "draft_id": draft.draft_id,
        },
        taxonomy_signals=taxonomy_signals,
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        draft_object_type=draft_type,
        requires_review=requires_review,
        confidence=confidence,
        errors=[],
        duplicate_key=duplicate_key,
    )
