import base64
import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.email_parsing.routing import classify_recipient_mailbox
from app.runtime.jsonl_store import read_json, runtime_path, write_json


GMAIL_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GMAIL_API_BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'


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


def _gmail_credentials_configured() -> bool:
    return bool(
        os.getenv('HERMES_GMAIL_CLIENT_ID')
        and os.getenv('HERMES_GMAIL_CLIENT_SECRET')
        and os.getenv('HERMES_GMAIL_REFRESH_TOKEN')
    )


def _get_gmail_access_token() -> str | None:
    client_id = os.getenv('HERMES_GMAIL_CLIENT_ID')
    client_secret = os.getenv('HERMES_GMAIL_CLIENT_SECRET')
    refresh_token = os.getenv('HERMES_GMAIL_REFRESH_TOKEN')

    if not (client_id and client_secret and refresh_token):
        return None

    payload = urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    }).encode('utf-8')

    request = Request(GMAIL_TOKEN_URL, data=payload, method='POST')
    request.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        with urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode('utf-8'))
    except Exception:
        return None

    return body.get('access_token')


def _gmail_api_get(path: str, access_token: str) -> dict[str, Any]:
    request = Request(f'{GMAIL_API_BASE}{path}', method='GET')
    request.add_header('Authorization', f'Bearer {access_token}')

    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))


def _history_cursor_path():
    return runtime_path('gmail', 'history_cursor.json')


def _load_last_history_id() -> str | None:
    record = read_json(_history_cursor_path())
    return record.get('history_id') if record else None


def _store_last_history_id(history_id: str) -> None:
    write_json(_history_cursor_path(), {'history_id': history_id})


def fetch_new_gmail_messages(notification_history_id: str | None) -> list[dict[str, Any]]:
    '''Fetches full message resources for whatever changed since the last
    processed historyId, using Gmail's history.list + messages.get.

    Cursor persistence: a Gmail Pub/Sub push notification carries only the
    mailbox's CURRENT historyId, not a delta -- finding what actually
    changed requires calling history.list with startHistoryId set to the
    LAST historyId Hermes successfully processed, not the one in this
    notification. That cursor is persisted at
    /hermes-runtime/gmail/history_cursor.json (via app.runtime.jsonl_store,
    the same mechanism app/drafts/service.py uses). On the very first
    notification ever received for a mailbox (no stored cursor yet) there
    is nothing to diff against -- this stores that notification's
    historyId as the baseline and returns [] rather than guessing at
    history from before Hermes started watching.

    Never raises: returns [] on missing credentials or any API failure, so
    a transient Gmail API error surfaces as "nothing to process this
    time" rather than a 500 from the webhook handler -- Pub/Sub redelivers
    push notifications on non-2xx anyway, so failing the whole request
    would just cause duplicate, not additional, delivery attempts.

    NOT verified against a live Gmail account -- no HERMES_GMAIL_*
    credentials exist in this environment. Written directly against the
    documented Gmail API contracts (history.list, messages.get); needs a
    real end-to-end pass once OAuth credentials are configured.
    '''
    if not _gmail_credentials_configured() or not notification_history_id:
        return []

    last_history_id = _load_last_history_id()
    if last_history_id is None:
        _store_last_history_id(notification_history_id)
        return []

    access_token = _get_gmail_access_token()
    if not access_token:
        return []

    try:
        history = _gmail_api_get(
            f'/history?startHistoryId={last_history_id}&historyTypes=messageAdded',
            access_token,
        )
    except Exception:
        return []

    message_ids: list[str] = []
    for record in history.get('history', []) or []:
        for added in record.get('messagesAdded', []) or []:
            message_id = (added.get('message') or {}).get('id')
            if message_id:
                message_ids.append(message_id)

    messages: list[dict[str, Any]] = []
    for message_id in message_ids:
        try:
            messages.append(_gmail_api_get(f'/messages/{message_id}?format=full', access_token))
        except Exception:
            continue

    _store_last_history_id(history.get('historyId') or notification_history_id)
    return messages


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
