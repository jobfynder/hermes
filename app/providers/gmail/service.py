import base64
import json
import os
from typing import Any

from app.email_parsing.routing import classify_recipient_mailbox


def gmail_provider_status() -> dict[str, Any]:
    configured = bool(
        os.getenv('HERMES_GMAIL_CLIENT_ID')
        and os.getenv('HERMES_GMAIL_CLIENT_SECRET')
        and os.getenv('HERMES_GMAIL_REFRESH_TOKEN')
    )

    return {
        'provider': 'gmail',
        'configured': configured,
        'status': 'configured' if configured else 'contract',
        'supports_webhook': True,
        'supports_files': True,
        'supports_outbound': False,
        'purpose': 'normalized_gmail_intake_contract',
        'parser_mode': 'deterministic',
        'uses_llm': False,
        'notification_mode': 'pubsub_push',
    }


def _decode_base64url(data: str) -> str:
    if not data:
        return ''

    padded = data + '=' * (-len(data) % 4)

    try:
        return base64.urlsafe_b64decode(padded.encode('utf-8')).decode('utf-8', errors='replace')
    except Exception:
        return ''


def _header_value(headers: list[dict[str, Any]], name: str) -> str | None:
    for header in headers or []:
        if (header.get('name') or '').lower() == name.lower():
            return header.get('value')

    return None


def _extract_plain_text_body(payload: dict[str, Any]) -> str:
    mime_type = payload.get('mimeType', '')
    body = payload.get('body') or {}

    if mime_type == 'text/plain' and body.get('data'):
        return _decode_base64url(body['data'])

    for part in payload.get('parts', []) or []:
        if part.get('mimeType') == 'text/plain':
            text = _extract_plain_text_body(part)
            if text:
                return text

    for part in payload.get('parts', []) or []:
        text = _extract_plain_text_body(part)
        if text:
            return text

    if body.get('data'):
        return _decode_base64url(body['data'])

    return ''


def normalize_gmail_message(message: dict[str, Any]) -> dict[str, Any]:
    '''Normalize a Gmail API users.messages.get resource (format=full) into
    the same shape normalize_email_payload() produces in
    app/providers/email/service.py, so it flows through the existing email
    intake pipeline (mailbox routing -> deterministic parsing) unchanged.

    Requires an already-fetched message resource. Gmail Pub/Sub push
    notifications only carry a historyId, not message content - fetching the
    message with an authenticated client is not yet wired in (see
    HERMES_GMAIL_* env vars in .env.example). This function is the reusable,
    testable normalization step for when that fetch is added.
    '''
    payload = message.get('payload') or {}
    headers = payload.get('headers') or []

    subject = _header_value(headers, 'Subject') or ''
    sender_raw = _header_value(headers, 'From') or ''
    to_raw = _header_value(headers, 'To') or ''

    sender_email = sender_raw
    if '<' in sender_raw and '>' in sender_raw:
        sender_email = sender_raw.split('<', 1)[1].split('>', 1)[0].strip()

    body_text = _extract_plain_text_body(payload) or message.get('snippet', '')
    intended_document_kind = classify_recipient_mailbox(to_raw)

    return {
        'channel': 'email',
        'source_message_id': str(message.get('id') or 'unknown'),
        'sender': {
            'sender_id': sender_email,
            'email': sender_email,
        },
        'content_type': 'text',
        'text': f'Subject: {subject}\n\n{body_text}'.strip(),
        'attachments': [],
        'received_at': message.get('internalDate'),
        'metadata': {
            'subject': subject,
            'to': to_raw,
            'provider': 'gmail',
            'intended_document_kind': intended_document_kind,
            'parser_mode': 'deterministic',
            'uses_llm': False,
            'thread_id': message.get('threadId'),
        },
    }


def parse_pubsub_push_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    '''Decode a Gmail Cloud Pub/Sub push notification envelope. This only
    reports that the mailbox history changed - it does NOT contain the
    message itself. Fetching the actual new message(s) requires an
    authenticated Gmail API client (HERMES_GMAIL_* credentials), not yet
    configured.
    '''
    message = envelope.get('message') or {}
    data = message.get('data') or ''
    decoded = _decode_base64url(data)

    try:
        payload = json.loads(decoded) if decoded else {}
    except Exception:
        payload = {}

    return {
        'email_address': payload.get('emailAddress'),
        'history_id': payload.get('historyId'),
        'pubsub_message_id': message.get('messageId'),
    }
