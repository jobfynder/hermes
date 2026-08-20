import os
import re
from typing import Any

from app.email_parsing.routing import classify_recipient_mailbox


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
