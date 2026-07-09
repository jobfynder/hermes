from typing import Any

from app.channels.adapters.base import BaseChannelAdapter
from app.channels.models import ChannelIntakeRequest


class GenericApiAdapter(BaseChannelAdapter):
    channel_name = "generic_api"

    def normalize(self, payload: dict[str, Any]) -> ChannelIntakeRequest:
        return ChannelIntakeRequest(**payload)
