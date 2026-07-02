from fastapi import APIRouter
from pydantic import BaseModel

from app.services.intent_service import detect_intent
from app.routers.jobs import parse_job_text

router = APIRouter()


class MessageUnderstandRequest(BaseModel):
    text: str


@router.post("/v1/messages/understand")
def understand_message(request: MessageUnderstandRequest):
    result = detect_intent(request.text)

    response = {
        "success": True,
        "text": request.text,
        "intent": result["intent"],
        "confidence": result["confidence"],
        "route": result["route"],
        "data": None,
    }

    if result["intent"] == "JOB":
        response["data"] = {
            "job": parse_job_text(request.text)
        }

    return response