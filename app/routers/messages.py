from fastapi import APIRouter
from pydantic import BaseModel

from app.services.intent_service import detect_intent

router = APIRouter()


class MessageUnderstandRequest(BaseModel):
    text: str


@router.post("/v1/messages/understand")
def understand_message(request: MessageUnderstandRequest):
    result = detect_intent(request.text)

    return {
        "success": True,
        "text": request.text,
        "intent": result["intent"],
        "confidence": result["confidence"],
        "route": result["route"],
    }