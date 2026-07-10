from pydantic import BaseModel

from fastapi import APIRouter

from app.providers.brightdata.service import (
    brightdata_provider_status,
    parse_public_linkedin_profile,
)


class BrightDataProfileParseRequest(BaseModel):
    public_profile_url: str


router = APIRouter(prefix="/providers/brightdata", tags=["BrightData Provider"])


@router.get("/status")
def brightdata_status() -> dict:
    return brightdata_provider_status()


@router.post("/linkedin-profile")
def parse_linkedin_profile(request: BrightDataProfileParseRequest) -> dict:
    return parse_public_linkedin_profile(request.public_profile_url)
