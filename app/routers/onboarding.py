from fastapi import APIRouter, HTTPException

from app.onboarding.models import (
    OnboardingProfileDraft,
    OnboardingProfileDraftRequest,
    OnboardingSession,
    OnboardingSessionRequest,
    OnboardingVerificationDraft,
    OnboardingVerificationDraftRequest,
)
from app.onboarding.service import (
    create_onboarding_session,
    create_profile_draft,
    get_onboarding_session,
    get_profile_draft,
    publish_profile_draft,
    create_verification_draft,
)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.post("/session", response_model=OnboardingSession)
def start_onboarding_session(request: OnboardingSessionRequest) -> OnboardingSession:
    return create_onboarding_session(request)


@router.get("/session/{session_id}", response_model=OnboardingSession)
def read_onboarding_session(session_id: str) -> OnboardingSession:
    session = get_onboarding_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Onboarding session not found")

    return session


@router.post("/profile/draft", response_model=OnboardingProfileDraft)
def create_onboarding_profile_draft(
    request: OnboardingProfileDraftRequest,
) -> OnboardingProfileDraft:
    return create_profile_draft(request)


@router.get("/profile/draft/{session_id}", response_model=OnboardingProfileDraft)
def read_onboarding_profile_draft(session_id: str) -> OnboardingProfileDraft:
    draft = get_profile_draft(session_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Onboarding profile draft not found")

    return draft


@router.post("/profile/publish/{session_id}")
def publish_onboarding_profile(session_id: str) -> dict:
    return publish_profile_draft(session_id)

@router.post("/verification/draft", response_model=OnboardingVerificationDraft)
def create_onboarding_verification_draft(
    request: OnboardingVerificationDraftRequest,
) -> OnboardingVerificationDraft:
    return create_verification_draft(request)

