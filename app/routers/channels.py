from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
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
    return get_supported_channels()


@router.post("/intake", response_model=ChannelIntakeResponse)
def channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    return process_channel_intake(request)


@router.post("/telegram/webhook", response_model=ChannelIntakeResponse)
def telegram_webhook(payload: dict[str, Any]) -> ChannelIntakeResponse:
    message = payload.get("message", {})
    chat = message.get("chat", {})
    sender = message.get("from", {})

    text = message.get("text") or message.get("caption") or ""
    source_message_id = str(message.get("message_id") or payload.get("update_id"))

    request = ChannelIntakeRequest(
        channel="telegram",
        source_message_id=source_message_id,
        sender={
            "sender_id": str(sender.get("id")) if sender.get("id") is not None else None,
            "sender_name": " ".join(
                part for part in [
                    sender.get("first_name"),
                    sender.get("last_name"),
                ]
                if part
            ) or None,
            "username": sender.get("username"),
        },
        conversation_id=str(chat.get("id")) if chat.get("id") is not None else None,
        content_type="text" if text else "unknown",
        text=text,
        metadata={
            "telegram_update_id": payload.get("update_id"),
            "telegram_chat_type": chat.get("type"),
        },
    )

    return process_channel_intake(request)



@router.post("/intake/file")
async def channel_file_intake(
    file: UploadFile = File(...),
    channel: str = Form("generic_api"),
    source_message_id: str = Form(...),
    document_kind: str = Form("unknown"),
):
    content = await file.read()

    return process_file_intake(
        filename=file.filename or "uploaded.txt",
        content=content,
        content_type=file.content_type,
        document_kind=document_kind,
        channel=channel,
        source_message_id=source_message_id,
    )
