from typing import Any

from app.channels.adapters.base import BaseChannelAdapter
from app.channels.models import ChannelIntakeRequest


class TelegramAdapter(BaseChannelAdapter):
    channel_name = "telegram"

    def normalize(self, payload: dict[str, Any]) -> ChannelIntakeRequest:
        message = payload.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})

        text = message.get("text") or message.get("caption") or ""
        source_message_id = str(message.get("message_id") or payload.get("update_id"))

        return ChannelIntakeRequest(
            channel="telegram",
            source_message_id=source_message_id,
            sender={
                "sender_id": str(sender.get("id")) if sender.get("id") is not None else None,
                "sender_name": " ".join(
                    part
                    for part in [
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
