from app.providers.models import ProviderHealth
from app.providers.telegram.service import telegram_provider_status
from app.providers.brightdata.service import brightdata_provider_status
from app.providers.gmail.service import gmail_provider_status
from app.providers.microsoft_graph.service import microsoft_graph_provider_status


PROVIDER_NAMES = [
    'telegram',
    'email',
    'gmail',
    'microsoft_graph',
    'whatsapp',
    'slack',
    'teams',
    'google_chat',
    'linkedin_oauth',
    'brightdata',
]


def telegram_health() -> ProviderHealth:
    status = telegram_provider_status()
    configured = bool(status.get('configured'))

    return ProviderHealth(
        provider='telegram',
        status='configured' if configured else 'not_configured',
        configured=configured,
        supports_webhook=True,
        supports_files=True,
        supports_outbound=True,
        webhook_url=status.get('webhook_url'),
        checks={
            'has_bot_token': status.get('has_bot_token'),
            'has_webhook_secret': status.get('has_webhook_secret'),
        },
        errors=[] if configured else ['telegram_not_configured'],
    )


def brightdata_health() -> ProviderHealth:
    status = brightdata_provider_status()
    configured = bool(status.get('configured'))

    return ProviderHealth(
        provider='brightdata',
        status='configured' if configured else 'contract',
        configured=configured,
        supports_webhook=False,
        supports_files=True,
        supports_outbound=False,
        webhook_url=None,
        checks={
            'has_api_key': status.get('has_api_key'),
            'has_profile_api_url': status.get('has_profile_api_url'),
            'uses_linkedin_oauth_token': status.get('uses_linkedin_oauth_token'),
        },
        errors=[] if configured else ['brightdata_not_configured'],
    )


def gmail_health() -> ProviderHealth:
    import os

    status = gmail_provider_status()
    configured = bool(status.get('configured'))

    return ProviderHealth(
        provider='gmail',
        status='configured' if configured else 'contract',
        configured=configured,
        supports_webhook=True,
        supports_files=False,
        supports_outbound=False,
        webhook_url=None,
        checks={
            'has_client_id': bool(os.getenv('HERMES_GMAIL_CLIENT_ID')),
            'has_client_secret': bool(os.getenv('HERMES_GMAIL_CLIENT_SECRET')),
            'has_refresh_token': bool(os.getenv('HERMES_GMAIL_REFRESH_TOKEN')),
            'notification_mode': status.get('notification_mode'),
        },
        errors=[] if configured else ['gmail_not_configured'],
    )


def microsoft_graph_health() -> ProviderHealth:
    import os

    status = microsoft_graph_provider_status()
    configured = bool(status.get('configured'))

    return ProviderHealth(
        provider='microsoft_graph',
        status='configured' if configured else 'contract',
        configured=configured,
        supports_webhook=True,
        supports_files=False,
        supports_outbound=False,
        webhook_url=None,
        checks={
            'has_client_id': bool(os.getenv('HERMES_MS_GRAPH_CLIENT_ID')),
            'has_client_secret': bool(os.getenv('HERMES_MS_GRAPH_CLIENT_SECRET')),
            'has_tenant_id': bool(os.getenv('HERMES_MS_GRAPH_TENANT_ID')),
            'notification_mode': status.get('notification_mode'),
        },
        errors=[] if configured else ['microsoft_graph_not_configured'],
    )


def contract_health(provider: str) -> ProviderHealth:
    return ProviderHealth(
        provider=provider,
        status='contract',
        configured=False,
        supports_webhook=provider in {'email', 'whatsapp', 'slack', 'teams', 'google_chat'},
        supports_files=provider in {'email', 'whatsapp', 'slack', 'teams', 'google_chat', 'brightdata'},
        supports_outbound=provider in {'email', 'whatsapp', 'slack', 'teams', 'google_chat'},
        webhook_url=None,
        checks={
            'implementation': 'pending',
        },
        errors=[],
    )


def get_provider_health(provider: str) -> ProviderHealth:
    if provider == 'telegram':
        return telegram_health()

    if provider == 'brightdata':
        return brightdata_health()

    if provider == 'gmail':
        return gmail_health()

    if provider == 'microsoft_graph':
        return microsoft_graph_health()

    if provider in PROVIDER_NAMES:
        return contract_health(provider)

    return ProviderHealth(
        provider=provider,
        status='failed',
        configured=False,
        errors=['unknown_provider'],
    )


def get_all_provider_health() -> list[ProviderHealth]:
    return [get_provider_health(provider) for provider in PROVIDER_NAMES]
