import json

from fastapi import APIRouter, Request

from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.channels.service import process_channel_intake
from app.security.fastapi_comm import require_comm_signature


router = APIRouter(prefix="/internal/comm", tags=["COMM Internal"])


@router.post("/intake", response_model=ChannelIntakeResponse)
async def comm_intake(request: Request) -> ChannelIntakeResponse:
    body = await require_comm_signature(request)
    payload = json.loads(body.decode("utf-8"))
    channel_request = ChannelIntakeRequest(**payload)
    return process_channel_intake(channel_request)
