from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.channels.adapters.registry import get_channel_adapter, list_channel_adapters
from app.channels.registry import get_supported_channels
from app.channels.service import process_channel_intake
from app.intake.service import process_file_intake

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.get("/health")
def channels_health() -> dict[str, str]:
    return {
        "status": "ok",
        "module": "HERMES-450",
        "component": "channel_intake",
    }


@router.get("/supported")
def supported_channels() -> dict[str, Any]:
    result = get_supported_channels()
    result["adapters"] = list_channel_adapters()
    return result


@router.post("/intake", response_model=ChannelIntakeResponse)
def channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    adapter = get_channel_adapter(request.channel)
    normalized = adapter.normalize(request.model_dump())
    return process_channel_intake(normalized)


@router.post("/telegram/webhook", response_model=ChannelIntakeResponse)
def telegram_webhook(payload: dict[str, Any]) -> ChannelIntakeResponse:
    adapter = get_channel_adapter("telegram")
    normalized = adapter.normalize(payload)
    return process_channel_intake(normalized)



@router.post("/intake/file")
async def channel_file_intake(
    file: UploadFile = File(...),
    channel: str = Form("generic_api"),
    source_message_id: str = Form(...),
    document_kind: str = Form("unknown"),
    actor_id: str | None = Form(None),
    role: str | None = Form(None),
    action: str | None = Form(None),
):
    content = await file.read()

    return process_file_intake(
        filename=file.filename or "uploaded.txt",
        content=content,
        content_type=file.content_type,
        document_kind=document_kind,
        channel=channel,
        source_message_id=source_message_id,
        actor_id=actor_id,
        role=role,
        action=action,
    )
