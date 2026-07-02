from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4

from app.services.consultant_service import parse_consultant_text

router = APIRouter()

HERMES_VERSION = "0.2.0"


class ConsultantParseRequest(BaseModel):
    text: str


def build_response(intent: str, confidence: float, route: str, data: dict):
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


@router.post("/v1/consultants/parse")
def parse_consultant(request: ConsultantParseRequest):
    return build_response(
        intent="RESUME",
        confidence=1.0,
        route="consultant_parser",
        data={
            "consultant": parse_consultant_text(request.text),
        },
    )