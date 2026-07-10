from fastapi import APIRouter

from app.providers.linkedin.service import (
    build_linkedin_authorization_url,
    exchange_linkedin_code,
    linkedin_provider_status,
)

router = APIRouter(prefix="/providers/linkedin", tags=["LinkedIn Provider"])


@router.get("/status")
def linkedin_status() -> dict:
    return linkedin_provider_status()


@router.get("/authorize")
def linkedin_authorize(state: str) -> dict:
    return build_linkedin_authorization_url(state)


@router.get("/callback")
def linkedin_callback(code: str, state: str | None = None) -> dict:
    result = exchange_linkedin_code(code)
    result["state"] = state
    return result
