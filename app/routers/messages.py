from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4

from app.services.intent_service import detect_intent
from app.routers.jobs import parse_job_text

router = APIRouter()

HERMES_VERSION = "0.2.0"


class MessageUnderstandRequest(BaseModel):
    text: str


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
def understand_message(request: MessageUnderstandRequest):
    result = detect_intent(request.text)

    data = None

    if result["intent"] == "JOB":
        data = {
            "job": parse_job_text(request.text),
        }

    return build_response(
        intent=result["intent"],
        confidence=result["confidence"],
        route=result["route"],
        data=data,
    )