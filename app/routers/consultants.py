from fastapi import APIRouter, Depends

from app.config import HERMES_VERSION
from app.security.rbac import require_permission
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import uuid4

from app.services.consultant_service import (
    merge_consultant_fallback_fields,
    parse_consultant_text,
    score_consultant_parse_confidence,
)
from app.understanding.llm_fallback import apply_llm_fallback
from app.understanding.models import ExtractedText

router = APIRouter()


CONSULTANT_PARSE_CONFIDENCE_THRESHOLD = 0.6


class ConsultantParseRequest(BaseModel):
    text: str


def build_response(intent: str, confidence: float, route: str, data: dict, fallback: dict | None = None):
    response = {
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

    if fallback is not None:
        response["fallback"] = fallback

    return response


@router.post("/v1/consultants/parse")
def parse_consultant(request: ConsultantParseRequest, user: dict = Depends(require_permission("consultants:parse"))):
    cleaned_text = request.text.strip()
    parsed = parse_consultant_text(cleaned_text)
    confidence, reasons = score_consultant_parse_confidence(cleaned_text, parsed)

    fallback_info: dict = {"action": "none", "should_call_llm": False, "llm_fallback": None}

    if confidence < CONSULTANT_PARSE_CONFIDENCE_THRESHOLD:
        fallback_info["action"] = "llm_structuring_candidate"
        fallback_info["should_call_llm"] = True
        fallback_info["reasons"] = reasons

        llm_outcome = apply_llm_fallback(
            document_kind="resume",
            extracted=ExtractedText(text=cleaned_text, source="plain_text"),
            source="v1_consultants_parse",
        )
        fallback_info["llm_fallback"] = llm_outcome

        if llm_outcome.get("used"):
            parsed = merge_consultant_fallback_fields(parsed, llm_outcome["extracted"])
            confidence = max(confidence, 0.75)

    return build_response(
        intent="RESUME",
        confidence=confidence,
        route="consultant_parser",
        data={"consultant": parsed},
        fallback=fallback_info,
    )
