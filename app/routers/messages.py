from fastapi import APIRouter, Depends

from app.config import HERMES_VERSION
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4

from app.services.intent_service import detect_intent
from app.security.rbac import require_permission
from app.routers.jobs import parse_job_text
from app.services.consultant_service import parse_consultant_text
from app.services.messaging_actions import extract_messaging_actions
from app.contracts.envelope import HermesCapabilityEnvelope, build_envelope

router = APIRouter()



class MessageUnderstandRequest(BaseModel):
    text: str


class MessageActionsExtractRequest(BaseModel):
    messages: list[str]
    allowed_actions: list[str] = []
    context: dict = {}


def build_response(intent: str, confidence: float, route: str, data: dict | None):
    return {
        "success": True,
        "request": {
            "id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "analysis": {
            "intent": intent,
            "confidence": confidence,
            "route": route,
        },
        "data": data,
        "metadata": {
            "version": HERMES_VERSION,
        },
    }


@router.post("/v1/messages/understand")
def understand_message(request: MessageUnderstandRequest, user: dict = Depends(require_permission("messages:understand"))):
    result = detect_intent(request.text)

    data = None

    if result["intent"] == "JOB":
        data = {
            "job": parse_job_text(request.text),
        }

    if result["intent"] == "RESUME":
        data = {
            "consultant": parse_consultant_text(request.text),
        }

    return build_response(
        intent=result["intent"],
        confidence=result["confidence"],
        route=result["route"],
        data=data,
    )

@router.post("/v1/messages/actions/extract", response_model=HermesCapabilityEnvelope)
def extract_message_actions(
    request: MessageActionsExtractRequest,
    user: dict = Depends(require_permission("messages:understand")),
) -> HermesCapabilityEnvelope:
    result = extract_messaging_actions(
        messages=request.messages,
        allowed_actions=request.allowed_actions,
        context=request.context,
    )
    llm_fallback = result.get("llm_fallback") or {}
    return build_envelope(
        capability="hermes.messaging.extract_actions",
        structured_data={"proposed_actions": result["proposed_actions"]},
        confidence=result["confidence"],
        llm_required=bool(llm_fallback.get("used")),
        llm_prompt_name="jf.messaging.actions.extract" if llm_fallback.get("used") else None,
        warnings=result["reasons"],
    )
