from app.security.rbac import require_admin_permission, require_service_permission
from pydantic import BaseModel

from fastapi import APIRouter, Depends

from app.providers.brightdata.service import (
    brightdata_provider_status,
    parse_public_linkedin_profile,
)


class BrightDataProfileParseRequest(BaseModel):
    public_profile_url: str


router = APIRouter(prefix="/providers/brightdata", tags=["BrightData Provider"])


@router.get("/status")
def brightdata_status(_principal: dict = Depends(require_admin_permission("runtime:read"))) -> dict:
    return brightdata_provider_status()


@router.post("/linkedin-profile")
def parse_linkedin_profile(request: BrightDataProfileParseRequest, _principal: dict = Depends(require_service_permission("understanding:parse"))) -> dict:
    return parse_public_linkedin_profile(request.public_profile_url)
