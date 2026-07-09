from app.providers.models import ProviderHealth
from app.providers.telegram.service import telegram_provider_status


PROVIDER_NAMES = [
    "telegram",
    "email",
    "whatsapp",
    "slack",
    "teams",
    "google_chat",
    "linkedin_oauth",
    "brightdata",
]


def telegram_health() -> ProviderHealth:
    status = telegram_provider_status()
    configured = bool(status.get("configured"))

    return ProviderHealth(
        provider="telegram",
        status="configured" if configured else "not_configured",
        configured=configured,
        supports_webhook=True,
        supports_files=True,
        supports_outbound=True,
        webhook_url=status.get("webhook_url"),
        checks={
            "has_bot_token": status.get("has_bot_token"),
            "has_webhook_secret": status.get("has_webhook_secret"),
        },
        errors=[] if configured else ["telegram_not_configured"],
    )


def contract_health(provider: str) -> ProviderHealth:
    return ProviderHealth(
        provider=provider,
        status="contract",
        configured=False,
        supports_webhook=provider in {"email", "whatsapp", "slack", "teams", "google_chat"},
        supports_files=provider in {"email", "whatsapp", "slack", "teams", "google_chat", "brightdata"},
        supports_outbound=provider in {"email", "whatsapp", "slack", "teams", "google_chat"},
        webhook_url=None,
        checks={
            "implementation": "pending",
        },
        errors=[],
    )


def get_provider_health(provider: str) -> ProviderHealth:
    if provider == "telegram":
        return telegram_health()

    if provider in PROVIDER_NAMES:
        return contract_health(provider)

    return ProviderHealth(
        provider=provider,
        status="failed",
        configured=False,
        errors=["unknown_provider"],
    )


def get_all_provider_health() -> list[ProviderHealth]:
    return [get_provider_health(provider) for provider in PROVIDER_NAMES]
