import base64
import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.email_parsing.html import html_to_text
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
        'notification_mode': 'pubsub_push_with_recent_reconciliation',
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


def _is_attachment(part: dict[str, Any]) -> bool:
    if (part.get('filename') or '').strip():
        return True
    disposition = _header_value(part.get('headers') or [], 'Content-Disposition') or ''
    return disposition.lower().lstrip().startswith('attachment')


def _find_mime_body(payload: dict[str, Any], wanted_type: str) -> str:
    if _is_attachment(payload):
        return ''
    mime_type = str(payload.get('mimeType') or '').split(';', 1)[0].strip().lower()
    body = payload.get('body') or {}
    if mime_type == wanted_type and body.get('data'):
        return _decode_base64url(body['data'])
    for part in payload.get('parts', []) or []:
        text = _find_mime_body(part, wanted_type)
        if text:
            return text
    return ''


def _extract_plain_text_body(payload: dict[str, Any]) -> str:
    # Prefer the sender's actual text/plain alternative. HTML-only mail is
    # common in forwarded Gmail messages, so convert that body before any
    # classifier or field extractor sees it. Attachments are never mistaken
    # for the message body.
    plain = _find_mime_body(payload, 'text/plain')
    if plain:
        return plain
    html = _find_mime_body(payload, 'text/html')
    if html:
        return html_to_text(html)
    mime_type = str(payload.get('mimeType') or '').lower()
    body = payload.get('body') or {}
    if not _is_attachment(payload) and mime_type.startswith('text/') and body.get('data'):
        decoded = _decode_base64url(body['data'])
        return html_to_text(decoded) if '<' in decoded and '>' in decoded else decoded
    return ''


def normalize_gmail_message(
    message: dict[str, Any], *, default_document_kind: str | None = None
) -> dict[str, Any]:
    '''Normalize a Gmail API users.messages.get resource (format=full) into
    the same shape normalize_email_payload() produces in
    app/providers/email/service.py, so it flows through the existing email
    intake pipeline (mailbox routing -> deterministic parsing) unchanged.

    Requires an already-fetched message resource. Gmail Pub/Sub push
    notifications carry only a historyId, while the scheduled reconciliation
    lists recent IDs; both paths fetch message content with the configured
    HERMES_GMAIL_* OAuth credentials before calling this normalizer.
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
    fallback_kind = (
        default_document_kind
        or os.getenv('HERMES_GMAIL_DEFAULT_DOCUMENT_KIND', '')
    ).strip().lower()
    if intended_document_kind == 'unknown' and fallback_kind in {
        'job_description', 'hotlist'
    }:
        intended_document_kind = fallback_kind

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


def _gmail_api_post(path: str, access_token: str) -> dict[str, Any]:
    request = Request(f'{GMAIL_API_BASE}{path}', data=b'', method='POST')
    request.add_header('Authorization', f'Bearer {access_token}')
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))


def list_gmail_message_ids(query: str, *, max_results: int = 10000) -> list[str]:
    """List message IDs matching a Gmail search query, newest first.

    This is the reconciliation counterpart to history.list. It deliberately
    searches a bounded recent window so a missed Pub/Sub notification, an
    expired history cursor, or the first-ever run cannot create a blind spot.
    Message content is fetched separately after the caller removes IDs Hermes
    has already recorded.
    """
    if not _gmail_credentials_configured() or max_results <= 0:
        return []

    access_token = _get_gmail_access_token()
    if not access_token:
        return []

    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_results:
        params = {
            'q': query,
            'maxResults': min(500, max_results - len(ids)),
        }
        if page_token:
            params['pageToken'] = page_token
        listing = _gmail_api_get(f"/messages?{urlencode(params)}", access_token)
        ids.extend(
            str(item['id'])
            for item in listing.get('messages', []) or []
            if item.get('id')
        )
        page_token = listing.get('nextPageToken')
        if not page_token:
            break
    return ids[:max_results]


def fetch_gmail_messages(message_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch full Gmail resources for a bounded set of message IDs."""
    if not message_ids or not _gmail_credentials_configured():
        return []
    access_token = _get_gmail_access_token()
    if not access_token:
        return []

    messages: list[dict[str, Any]] = []
    for message_id in message_ids:
        try:
            messages.append(
                _gmail_api_get(f'/messages/{message_id}?format=full', access_token)
            )
        except Exception:
            # The next reconciliation run retries any ID that never reached
            # intake_log, so one deleted/transient message cannot block a page.
            continue
    return messages


def trash_gmail_messages(message_ids: list[str]) -> tuple[int, list[str]]:
    """Move message IDs to Gmail Trash; requires the gmail.modify scope."""
    if not message_ids or not _gmail_credentials_configured():
        return 0, list(message_ids)
    access_token = _get_gmail_access_token()
    if not access_token:
        return 0, list(message_ids)
    moved = 0
    failed: list[str] = []
    for message_id in message_ids:
        try:
            _gmail_api_post(f'/messages/{message_id}/trash', access_token)
            moved += 1
        except Exception:
            failed.append(message_id)
    return moved, failed


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
