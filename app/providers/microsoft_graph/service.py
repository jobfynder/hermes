import json
import os
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.email_parsing.routing import classify_recipient_mailbox


GRAPH_TOKEN_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
GRAPH_API_BASE = 'https://graph.microsoft.com/v1.0'


def microsoft_graph_provider_status() -> dict[str, Any]:
    configured = bool(
        os.getenv('HERMES_MS_GRAPH_CLIENT_ID')
        and os.getenv('HERMES_MS_GRAPH_CLIENT_SECRET')
        and os.getenv('HERMES_MS_GRAPH_TENANT_ID')
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
    }


def _strip_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


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
