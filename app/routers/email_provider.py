import json

from fastapi import APIRouter, Request

from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.channels.service import process_channel_intake
from app.providers.email.service import email_provider_status, normalize_email_payload
from app.security.fastapi_comm import require_comm_signature

router = APIRouter(prefix="/providers/email", tags=["Email Provider"])


@router.get("/status")
def email_status() -> dict:
    return email_provider_status()


@router.post("/webhook", response_model=ChannelIntakeResponse)
async def email_webhook(request: Request) -> ChannelIntakeResponse:
    body = await require_comm_signature(request)
    payload = json.loads(body.decode("utf-8"))
    normalized = normalize_email_payload(payload)
    channel_request = ChannelIntakeRequest(**normalized)
    return process_channel_intake(channel_request)
