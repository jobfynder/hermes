from uuid import uuid4

from app.drafts.service import create_draft_object
from app.runtime.events import emit_event
from app.runtime.intake_log import record_intake
from app.onboarding.models import (
    OnboardingProfileDraft,
    OnboardingProfileDraftRequest,
    OnboardingSession,
    OnboardingSessionRequest,
)
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


_sessions: dict[str, OnboardingSession] = {}
_drafts: dict[str, OnboardingProfileDraft] = {}


def create_onboarding_session(request: OnboardingSessionRequest) -> OnboardingSession:
    session = OnboardingSession(
        session_id=str(uuid4()),
        user_id=request.user_id,
        role=request.role,
        channel=request.channel,
        channel_user_id=request.channel_user_id,
        sender_name=request.sender_name,
        status="role_selected" if request.role != "unknown" else "started",
        metadata=request.metadata,
    )
    _sessions[session.session_id] = session
    record_intake(
        {
            "status": "onboarding_session_created",
            "session_id": session.session_id,
            "role": session.role,
            "channel": session.channel,
            "channel_user_id": session.channel_user_id,
        }
    )
    emit_event(
        "onboarding.session.created",
        {
            "session_id": session.session_id,
            "role": session.role,
            "channel": session.channel,
        },
    )
    return session


def get_onboarding_session(session_id: str) -> OnboardingSession | None:
    return _sessions.get(session_id)


def _infer_display_name(profile_text: str) -> str | None:
    for line in profile_text.splitlines():
        cleaned = line.strip()
        if cleaned and len(cleaned.split()) <= 5:
            return cleaned
    return None


def _infer_headline(profile_text: str, role: str) -> str:
    lowered = profile_text.lower()

    if "bench sales" in lowered:
        return "Bench Sales Recruiter"
    if "recruiter" in lowered:
        return "Recruiter"
    if "consultant" in lowered:
        return "Consultant"
    if role == "bench_sales":
        return "Bench Sales Recruiter"
    if role == "recruiter":
        return "Recruiter"
    if role == "consultant":
        return "Consultant"

    return "Jobfynder Member"


def _infer_specializations(skills: list[str], profile_text: str, role: str) -> list[str]:
    specializations: list[str] = []
    lowered = profile_text.lower()

    if "us it staffing" in lowered:
        specializations.append("US IT Staffing")
    if "bench sales" in lowered or role == "bench_sales":
        specializations.append("Bench Sales")
    if "vendor" in lowered:
        specializations.append("Vendor Management")
    if "recruiter" in lowered or role == "recruiter":
        specializations.append("Recruiting")

    for skill in skills:
        if skill not in specializations:
            specializations.append(skill)

    return specializations[:10]


def create_profile_draft(request: OnboardingProfileDraftRequest) -> OnboardingProfileDraft:
    session = get_onboarding_session(request.session_id)

    if not session:
        return OnboardingProfileDraft(
            session_id=request.session_id,
            role=request.role,
            created_from=request.source,
            requires_review=True,
            confidence=0.0,
            errors=["onboarding_session_not_found"],
        )

    understanding = understand_document(
        RawDocument(
            content=request.profile_text,
            filename=None,
            content_type="text/plain",
            document_kind="recruiter_profile" if request.role in {"bench_sales", "recruiter"} else "consultant_profile",
        )
    )

    understanding_dict = understanding.model_dump()
    structured_data = understanding_dict.get("structured_data", {})
    taxonomy_signals = structured_data.get("taxonomy_signals", {})
    normalized_skills = structured_data.get("normalized_skills", [])
    quality = understanding_dict.get("quality", {})
    confidence = float(quality.get("confidence") or 0.75)

    draft = OnboardingProfileDraft(
        session_id=request.session_id,
        role=request.role,
        display_name=_infer_display_name(request.profile_text),
        headline=_infer_headline(request.profile_text, request.role),
        company=None,
        location=structured_data.get("location"),
        summary=request.profile_text.strip()[:800],
        specializations=_infer_specializations(
            skills=normalized_skills,
            profile_text=request.profile_text,
            role=request.role,
        ),
        skills=normalized_skills,
        trust_signals={
            "profile_prefilled": True,
            "user_review_required": True,
            "source": request.source,
        },
        created_from=request.source,
        requires_review=True,
        confidence=confidence,
        understanding_result=understanding_dict,
        taxonomy_signals=taxonomy_signals,
        errors=[],
    )

    draft_object = create_draft_object(
        draft_type="draft_bench_sales_profile" if request.role == "bench_sales" else (
            "draft_recruiter_profile" if request.role == "recruiter" else "draft_consultant_profile"
        ),
        source="onboarding_profile_text",
        source_ref=request.session_id,
        channel=session.channel,
        source_message_id=request.session_id,
        payload=draft.model_dump(),
        normalized_skills=draft.skills,
        normalized_job_titles=[],
        taxonomy_signals=taxonomy_signals,
        confidence=confidence,
        requires_review=True,
        metadata={
            "onboarding_session_id": request.session_id,
            "created_from": request.source,
        },
    )

    draft.trust_signals = {
        **draft.trust_signals,
        "draft_object_id": draft_object.draft_id,
    }

    _drafts[request.session_id] = draft
    session.status = "draft_created"
    _sessions[session.session_id] = session
    record_intake(
        {
            "status": "onboarding_draft_created",
            "session_id": request.session_id,
            "role": request.role,
            "source": request.source,
            "draft_object_id": draft_object.draft_id,
            "skills": draft.skills,
            "confidence": draft.confidence,
        }
    )
    emit_event(
        "onboarding.draft.created",
        {
            "session_id": request.session_id,
            "role": request.role,
            "draft_object_id": draft_object.draft_id,
        },
    )

    return draft


def get_profile_draft(session_id: str) -> OnboardingProfileDraft | None:
    return _drafts.get(session_id)


def publish_profile_draft(session_id: str) -> dict:
    draft = get_profile_draft(session_id)
    session = get_onboarding_session(session_id)

    if not draft:
        return {
            "status": "blocked",
            "reason": "draft_not_found",
            "session_id": session_id,
        }

    missing_fields = [
        field
        for field in ["role", "headline"]
        if not getattr(draft, field)
    ]

    if missing_fields:
        return {
            "status": "blocked",
            "reason": "missing_required_fields",
            "missing_fields": missing_fields,
            "session_id": session_id,
        }

    if session:
        session.status = "published"
        _sessions[session.session_id] = session

    return {
        "status": "published",
        "session_id": session_id,
        "profile_status": "published",
        "requires_user_review": False,
        "draft": draft.model_dump(),
    }
