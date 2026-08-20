from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.channels.broadcast_extraction import (
    extract_broadcast_hotlist,
    extract_broadcast_requirement,
)
from app.contracts.envelope import HermesCapabilityEnvelope, build_envelope
from app.security.rbac import require_permission

router = APIRouter(prefix="/broadcast", tags=["Broadcast"])


class BroadcastMessageRequest(BaseModel):
    message: str


@router.post("/requirement/extract", response_model=HermesCapabilityEnvelope)
def broadcast_requirement_extract(
    request: BroadcastMessageRequest,
    _user: dict = Depends(require_permission("broadcast:extract")),
) -> HermesCapabilityEnvelope:
    result = extract_broadcast_requirement(request.message)
    llm_fallback = result.get("llm_fallback") or {}
    return build_envelope(
        capability="hermes.broadcast.parse_requirement",
        structured_data=result["structured_data"],
        confidence=result["confidence"],
        llm_required=bool(llm_fallback.get("used")),
        llm_prompt_name="jf.broadcast.requirement.extract" if llm_fallback.get("used") else None,
    )


@router.post("/hotlist/extract", response_model=HermesCapabilityEnvelope)
def broadcast_hotlist_extract(
    request: BroadcastMessageRequest,
    _user: dict = Depends(require_permission("broadcast:extract")),
) -> HermesCapabilityEnvelope:
    result = extract_broadcast_hotlist(request.message)
    llm_fallback = result.get("llm_fallback") or {}
    return build_envelope(
        capability="hermes.broadcast.parse_hotlist",
        structured_data=result["structured_data"],
        confidence=result["confidence"],
        llm_required=bool(llm_fallback.get("used")),
        llm_prompt_name="jf.broadcast.hotlist.extract" if llm_fallback.get("used") else None,
    )
