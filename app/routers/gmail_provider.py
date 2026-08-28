import json

from fastapi import APIRouter, Request

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.gmail.service import (
    fetch_new_gmail_messages,
    gmail_provider_status,
    normalize_gmail_message,
    parse_pubsub_push_envelope,
)

router = APIRouter(prefix='/providers/gmail', tags=['Gmail Provider'])


@router.get('/status')
def gmail_status() -> dict:
    return gmail_provider_status()


@router.post('/push')
async def gmail_push(request: Request) -> dict:
    '''Cloud Pub/Sub push endpoint for Gmail mailbox change notifications.

    No auth dependency here on purpose -- this is called by Google Cloud
    Pub/Sub, not by an authenticated Hermes client, matching
    /providers/email/webhook's use of signature verification instead of a
    bearer token. Always acknowledges receipt (Pub/Sub redelivers on
    non-2xx) even when nothing could be fetched/processed.
    '''
    body = await request.body()
    envelope = json.loads(body.decode('utf-8')) if body else {}
    parsed = parse_pubsub_push_envelope(envelope)

    status = gmail_provider_status()

    processed: list[dict] = []
    if status['configured']:
        for message in fetch_new_gmail_messages(parsed.get('history_id')):
            normalized = normalize_gmail_message(message)
            channel_request = ChannelIntakeRequest(**normalized)
            result = process_channel_intake(channel_request)
            processed.append({
                'source_message_id': result.source_message_id,
                'intake_status': result.intake_status,
                'document_kind': result.document_kind,
                'draft_object_type': result.draft_object_type,
            })

    return {
        'acknowledged': True,
        'configured': status['configured'],
        'history_id': parsed.get('history_id'),
        'email_address': parsed.get('email_address'),
        'processed_count': len(processed),
        'processed': processed,
        'note': (
            'Notification received but not fetched - Gmail API credentials '
            'not configured. See HERMES_GMAIL_* in .env.example.'
            if not status['configured']
            else None
        ),
    }
