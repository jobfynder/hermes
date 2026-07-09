from typing import Any

from app.channels.adapters.base import BaseChannelAdapter
from app.channels.models import ChannelIntakeRequest


class ContractAdapter(BaseChannelAdapter):
    def __init__(self, channel_name: str) -> None:
        self.channel_name = channel_name

    def normalize(self, payload: dict[str, Any]) -> ChannelIntakeRequest:
        return ChannelIntakeRequest(
            channel=self.channel_name,
            source_message_id=str(payload.get("source_message_id") or payload.get("id") or "unknown"),
            sender=payload.get("sender", {}),
            workspace_id=payload.get("workspace_id"),
            conversation_id=payload.get("conversation_id"),
            content_type=payload.get("content_type", "unknown"),
            text=payload.get("text"),
            attachments=payload.get("attachments", []),
            received_at=payload.get("received_at"),
            raw_payload_ref=payload.get("raw_payload_ref"),
            metadata={
                **payload.get("metadata", {}),
                "adapter_status": "contract",
                "raw_provider_payload": payload,
            },
        )
