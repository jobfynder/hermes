import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.email_parsing.routing import classify_recipient_mailbox
from app.runtime.jsonl_store import read_json, runtime_path, write_json


GRAPH_TOKEN_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
GRAPH_API_BASE = 'https://graph.microsoft.com/v1.0'

# Graph's own documented max subscription lifetime for Outlook mail
# resources is 4230 minutes (~2.94 days). Renewing at 24h remaining gives
# a wide safety margin for a daily renewal job to catch it.
MAX_MESSAGE_SUBSCRIPTION_MINUTES = 4230
RENEW_WITHIN = timedelta(hours=24)


def microsoft_graph_provider_status() -> dict[str, Any]:
    configured = bool(
        os.getenv('HERMES_MS_GRAPH_CLIENT_ID')
        and os.getenv('HERMES_MS_GRAPH_CLIENT_SECRET')
        and os.getenv('HERMES_MS_GRAPH_TENANT_ID')
    )
    subscriptions_configured = bool(
        configured
        and _notification_url()
        and _client_state()
        and configured_mailboxes()
    )

    return {
        'provider': 'microsoft_graph',
        'configured': configured,
        'status': 'configured' if configured else 'contract',
        'supports_webhook': True,
        'supports_files': True,
        'supports_outbound': False,
        'purpose': 'normalized_office365_intake_contract',
        'parser_mode': 'deterministic',
        'uses_llm': False,
        'notification_mode': 'graph_change_notifications',
        'subscriptions_configured': subscriptions_configured,
        'mailboxes': configured_mailboxes(),
    }


def _strip_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


def _graph_credentials_configured() -> bool:
    return bool(
        os.getenv('HERMES_MS_GRAPH_CLIENT_ID')
        and os.getenv('HERMES_MS_GRAPH_CLIENT_SECRET')
        and os.getenv('HERMES_MS_GRAPH_TENANT_ID')
    )


def _get_graph_access_token() -> str | None:
    client_id = os.getenv('HERMES_MS_GRAPH_CLIENT_ID')
    client_secret = os.getenv('HERMES_MS_GRAPH_CLIENT_SECRET')
    tenant_id = os.getenv('HERMES_MS_GRAPH_TENANT_ID')

    if not (client_id and client_secret and tenant_id):
        return None

    payload = urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }).encode('utf-8')

    request = Request(
        GRAPH_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id),
        data=payload,
        method='POST',
    )
    request.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        with urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode('utf-8'))
    except Exception:
        return None

    return body.get('access_token')


def fetch_graph_message(resource: str | None) -> dict[str, Any] | None:
    '''Fetches the full message resource referenced by a Graph change
    notification. `resource` is the notification's own `resource` field
    (e.g. "Users/{id}/Messages/{message-id}"), fetched directly against
    Graph's v1.0 endpoint.

    Uses app-only auth (client credentials grant), not delegated auth --
    there's no interactive user in a webhook handler. This requires the
    app registration to be granted the Mail.Read *application* permission
    (admin-consented) on the tenant, not just Mail.Read as a delegated
    scope; that consent step happens in Azure AD, not in this code.

    Returns None (never raises) on missing credentials, a missing
    resource, or any API failure -- same "treat as nothing to process"
    reasoning as the Gmail fetch in app/providers/gmail/service.py.

    NOT verified against a live Microsoft 365 tenant -- no
    HERMES_MS_GRAPH_* credentials exist in this environment. Written
    directly against Graph's documented v1.0 message-resource and
    client-credentials contracts; needs a real end-to-end pass once an
    app registration and tenant credentials exist.
    '''
    access_token = _get_graph_access_token()
    if not access_token or not resource:
        return None

    request = Request(f'{GRAPH_API_BASE}/{resource.lstrip("/")}', method='GET')
    request.add_header('Authorization', f'Bearer {access_token}')

    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None


def configured_mailboxes() -> list[str]:
    raw = os.getenv('HERMES_MS_GRAPH_MAILBOXES', '')
    return [mailbox.strip() for mailbox in raw.split(',') if mailbox.strip()]


def _client_state() -> str | None:
    return os.getenv('HERMES_MS_GRAPH_CLIENT_STATE') or None


def _notification_url() -> str | None:
    # Read dynamically (not via app.config's module-level constant) so
    # this stays consistent with every other env var this module reads,
    # and so it can be set/unset per-test without reloading modules.
    base_url = os.getenv('HERMES_PUBLIC_WEBHOOK_BASE_URL')
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/providers/microsoft-graph/webhook"


def verify_notification_client_state(notification: dict[str, Any]) -> bool:
    '''Graph's own anti-spoofing mechanism: every subscription is created
    with a clientState value, and every change notification Graph sends
    for it echoes that value back. Without checking this, anyone who finds
    the (unauthenticated, necessarily-public) webhook URL could POST a
    forged notification and make Hermes fetch and ingest whatever message
    they choose, using this app's own Mail.Read grant. Returns False (do
    not process) if no clientState is configured at all, not just on a
    mismatch -- an unconfigured secret is not an open invitation.
    '''
    expected = _client_state()
    return bool(expected) and notification.get('clientState') == expected


def _subscriptions_path():
    return runtime_path('microsoft_graph', 'subscriptions.json')


def _load_stored_subscriptions() -> dict[str, Any]:
    return read_json(_subscriptions_path()) or {}


def _store_subscriptions(data: dict[str, Any]) -> None:
    write_json(_subscriptions_path(), data)


def _graph_api_request(
    method: str,
    path: str,
    access_token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = Request(f'{GRAPH_API_BASE}{path}', data=data, method=method)
    request.add_header('Authorization', f'Bearer {access_token}')
    if data is not None:
        request.add_header('Content-Type', 'application/json')

    with urlopen(request, timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def sync_graph_subscriptions() -> dict[str, Any]:
    '''Creates a Graph change-notification subscription for every mailbox
    in HERMES_MS_GRAPH_MAILBOXES that doesn't have one yet, and renews
    (PATCH expirationDateTime) any that expire within RENEW_WITHIN.
    Already-fresh subscriptions are left untouched. Idempotent -- safe to
    call repeatedly, e.g. from a daily host cron running
    scripts/hermes-850-graph-subscription-renew.py, which is required
    infrastructure here, not optional: without it, notifications silently
    stop arriving once the subscription expires (~3 days for mail) and
    nothing else in this codebase would re-create it.

    Returns {'status': 'blocked', 'reason': ...} without calling Graph at
    all if credentials, the notification URL, the clientState secret, or
    the mailbox list aren't all configured.
    '''
    notification_url = _notification_url()
    client_state = _client_state()
    mailboxes = configured_mailboxes()

    if not _graph_credentials_configured():
        return {'status': 'blocked', 'reason': 'graph_credentials_not_configured'}
    if not notification_url:
        return {'status': 'blocked', 'reason': 'HERMES_PUBLIC_WEBHOOK_BASE_URL_not_set'}
    if not client_state:
        return {'status': 'blocked', 'reason': 'HERMES_MS_GRAPH_CLIENT_STATE_not_set'}
    if not mailboxes:
        return {'status': 'blocked', 'reason': 'HERMES_MS_GRAPH_MAILBOXES_not_set'}

    stored = _load_stored_subscriptions()
    results: dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    expiration = (
        now + timedelta(minutes=MAX_MESSAGE_SUBSCRIPTION_MINUTES)
    ).strftime('%Y-%m-%dT%H:%M:%S.0000000Z')

    # Acquired lazily, once, only if at least one mailbox actually needs an
    # API call this run -- avoids a pointless token exchange when every
    # subscription is already fresh.
    access_token: str | None = None

    for mailbox in mailboxes:
        existing = stored.get(mailbox)

        if existing and existing.get('id'):
            expires_at = datetime.fromisoformat(
                existing['expirationDateTime'].replace('Z', '+00:00')
            )
            if expires_at - now > RENEW_WITHIN:
                results[mailbox] = {'status': 'still_valid', **existing}
                continue

        if access_token is None:
            access_token = _get_graph_access_token()
            if not access_token:
                results[mailbox] = {'status': 'failed', 'error': 'token_acquisition_failed'}
                continue

        try:
            if existing and existing.get('id'):
                updated = _graph_api_request(
                    'PATCH',
                    f"/subscriptions/{existing['id']}",
                    access_token,
                    {'expirationDateTime': expiration},
                )
                stored[mailbox] = {
                    'id': existing['id'],
                    'expirationDateTime': updated.get('expirationDateTime', expiration),
                }
                results[mailbox] = {'status': 'renewed', **stored[mailbox]}
            else:
                created = _graph_api_request(
                    'POST',
                    '/subscriptions',
                    access_token,
                    {
                        'changeType': 'created',
                        'notificationUrl': notification_url,
                        'resource': f"users/{mailbox}/mailFolders('Inbox')/messages",
                        'expirationDateTime': expiration,
                        'clientState': client_state,
                    },
                )
                stored[mailbox] = {
                    'id': created.get('id'),
                    'expirationDateTime': created.get('expirationDateTime', expiration),
                }
                results[mailbox] = {'status': 'created', **stored[mailbox]}
        except Exception as exc:
            results[mailbox] = {'status': 'failed', 'error': str(exc)}

    _store_subscriptions(stored)
    return {'status': 'completed', 'mailboxes': results}


def list_stored_subscriptions() -> dict[str, Any]:
    return _load_stored_subscriptions()


def normalize_graph_message(message: dict[str, Any]) -> dict[str, Any]:
    '''Normalize a Microsoft Graph message resource (from GET
    /me/messages/{id} or /users/{id}/messages/{id}) into the same shape
    normalize_email_payload() produces in app/providers/email/service.py, so
    it flows through the existing email intake pipeline unchanged.

    Graph change notifications only carry a resource reference, not the
    message body - fetching the full message requires an authenticated
    Graph client (HERMES_MS_GRAPH_* credentials), not yet configured. This
    function is the reusable normalization step for when that fetch is
    added.
    '''
    subject = message.get('subject') or ''
    body = message.get('body') or {}
    body_content = body.get('content') or message.get('bodyPreview') or ''

    if (body.get('contentType') or '').lower() == 'html':
        body_content = _strip_html(body_content)

    sender = (message.get('from') or {}).get('emailAddress') or {}
    to_recipients = [
        (recipient.get('emailAddress') or {}).get('address')
        for recipient in message.get('toRecipients', [])
        if recipient.get('emailAddress')
    ]

    intended_document_kind = classify_recipient_mailbox(to_recipients)

    return {
        'channel': 'email',
        'source_message_id': str(message.get('id') or 'unknown'),
        'sender': {
            'sender_id': sender.get('address'),
            'email': sender.get('address'),
            'sender_name': sender.get('name'),
        },
        'content_type': 'text',
        'text': f'Subject: {subject}\n\n{body_content}'.strip(),
        'attachments': [],
        'received_at': message.get('receivedDateTime'),
        'metadata': {
            'subject': subject,
            'to': to_recipients,
            'provider': 'microsoft_graph',
            'intended_document_kind': intended_document_kind,
            'parser_mode': 'deterministic',
            'uses_llm': False,
            'conversation_id': message.get('conversationId'),
        },
    }
