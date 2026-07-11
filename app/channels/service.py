import re

from app.access.models import ActionAccessRequest
from app.access.service import authorize_action
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


_JOB_STRONG_MARKERS = (
    "job description",
    "job opening",
    "job requirement",
    "job posting",
    "opening for",
    "hiring for",
    "we are hiring",
    "looking for a",
    "looking for an",
    "seeking a",
    "seeking an",
    "position available",
    "required skills",
    "must have",
    "nice to have",
    "responsibilities",
    "requirements",
    "contract duration",
    "contract length",
    "hourly rate",
    "pay rate",
    "client location",
    "work location",
)

_RESUME_STRONG_MARKERS = (
    "resume",
    "curriculum vitae",
    "professional summary",
    "career objective",
    "work experience",
    "employment history",
    "education",
    "technical skills",
)

_HOTLIST_MARKERS = (
    "hotlist",
    "available consultants",
    "bench list",
)

_VENDOR_MARKERS = (
    "vendor list",
    "implementation partner",
    "prime vendor",
)

_PROFILE_CUES = (
    "candidate",
    "consultant",
    "available immediately",
    "on bench",
    "my experience",
    "i have ",
    "i am ",
    "email:",
    "phone:",
    "linkedin",
    "professional summary",
    "work experience",
    "employment history",
    "education",
    "resume",
    "curriculum vitae",
)

_TECHNOLOGY_MARKERS = (
    "java",
    "spring boot",
    "python",
    ".net",
    "c#",
    "c++",
    "javascript",
    "typescript",
    "node.js",
    "nodejs",
    "react",
    "angular",
    "aws",
    "azure",
    "gcp",
    "sql",
    "postgresql",
    "mysql",
    "oracle",
    "docker",
    "kubernetes",
    "terraform",
    "jenkins",
    "kafka",
    "salesforce",
    "sap",
    "snowflake",
    "databricks",
    "devops",
    "linux",
    "golang",
    "ruby",
    "php",
)

_TITLE_PATTERN = re.compile(
    r"\b(?:senior|sr\.?|lead|principal|staff|junior|jr\.?|mid(?:-level)?)?"
    r"\s*(?:[a-z0-9+#.\-]+\s+){0,3}"
    r"(?:developer|engineer|architect|analyst|administrator|consultant|"
    r"manager|recruiter|scientist|designer|specialist)\b",
    re.IGNORECASE,
)

_EXPERIENCE_PATTERN = re.compile(
    r"\b\d{1,2}\+?\s*(?:years?|yrs?)"
    r"(?:\s+of)?(?:\s+(?:professional\s+)?)?experience\b",
    re.IGNORECASE,
)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _marker_count(text: str, markers: tuple[str, ...]) -> int:
    return sum(1 for marker in markers if marker in text)


def _technology_count(text: str) -> int:
    count = 0

    for marker in _TECHNOLOGY_MARKERS:
        pattern = rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            count += 1

    return count


def detect_document_kind(request: ChannelIntakeRequest) -> DocumentKind:
    text = " ".join((request.text or "").lower().split())

    if not text:
        return "unknown"

    if _contains_marker(text, _HOTLIST_MARKERS):
        return "hotlist"

    if _contains_marker(text, _VENDOR_MARKERS):
        return "vendor_list"

    job_marker_count = _marker_count(text, _JOB_STRONG_MARKERS)
    resume_marker_count = _marker_count(text, _RESUME_STRONG_MARKERS)

    if job_marker_count and not resume_marker_count:
        return "job_description"

    if resume_marker_count and not job_marker_count:
        return "resume"

    if job_marker_count and resume_marker_count:
        if job_marker_count > resume_marker_count:
            return "job_description"
        return "resume"

    if "bench sales" in text:
        return "bench_sales_profile"

    if "recruiter" in text and not _TITLE_PATTERN.search(text):
        return "recruiter_profile"

    has_title = bool(_TITLE_PATTERN.search(text))
    has_experience = bool(_EXPERIENCE_PATTERN.search(text))
    technology_count = _technology_count(text)
    has_profile_cue = _contains_marker(text, _PROFILE_CUES)

    if has_title and has_experience and technology_count >= 3:
        if has_profile_cue:
            return "resume"
        return "job_description"

    return "plain_message"

def understanding_document_kind(document_kind: DocumentKind) -> str:
    if document_kind in {"resume", "job_description", "unknown"}:
        return document_kind

    return "message"

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


def enforce_optional_action_access(request: ChannelIntakeRequest) -> list[str]:
    if not request.actor_id and not request.role and not request.action:
        return []

    if not request.actor_id or not request.role or not request.action:
        return ["access_context_incomplete"]

    decision = authorize_action(
        ActionAccessRequest(
            actor_id=request.actor_id,
            role=request.role,
            action=request.action,
            channel=request.channel,
            metadata={
                "source_message_id": request.source_message_id,
            },
        )
    )

    if decision.status != "allowed":
        return [decision.reason or "action_not_allowed"]

    return []


def process_channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    duplicate_key = build_duplicate_key(request)

    access_errors = enforce_optional_action_access(request)
    if access_errors:
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="failed",
            document_kind="unknown",
            draft_object_type="draft_channel_note",
            requires_review=True,
            confidence=0.0,
            errors=access_errors,
            duplicate_key=duplicate_key,
        )

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
            document_kind=understanding_document_kind(document_kind),
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
