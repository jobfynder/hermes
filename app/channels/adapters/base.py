from abc import ABC, abstractmethod
from typing import Any

from app.channels.models import ChannelIntakeRequest


class BaseChannelAdapter(ABC):
    channel_name: str

    @abstractmethod
    def normalize(self, payload: dict[str, Any]) -> ChannelIntakeRequest:
        """Normalize a provider-specific payload into Hermes canonical intake."""
        raise NotImplementedError
