from app.channels.adapters.base import BaseChannelAdapter
from app.channels.adapters.contracts import ContractAdapter
from app.channels.adapters.generic import GenericApiAdapter
from app.channels.adapters.telegram import TelegramAdapter


_ADAPTERS: dict[str, BaseChannelAdapter] = {
    "generic_api": GenericApiAdapter(),
    "telegram": TelegramAdapter(),
    "email": ContractAdapter("email"),
    "whatsapp": ContractAdapter("whatsapp"),
    "slack": ContractAdapter("slack"),
    "teams": ContractAdapter("teams"),
    "google_chat": ContractAdapter("google_chat"),
    "browser_extension": ContractAdapter("browser_extension"),
    "web_upload": ContractAdapter("web_upload"),
}


def get_channel_adapter(channel_name: str) -> BaseChannelAdapter:
    try:
        return _ADAPTERS[channel_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported channel adapter: {channel_name}") from exc


def list_channel_adapters() -> list[str]:
    return sorted(_ADAPTERS.keys())
