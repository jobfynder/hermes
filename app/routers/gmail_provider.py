import json

from fastapi import APIRouter, Request

from app.providers.gmail.service import gmail_provider_status, parse_pubsub_push_envelope

router = APIRouter(prefix='/providers/gmail', tags=['Gmail Provider'])


@router.get('/status')
def gmail_status() -> dict:
    return gmail_provider_status()


@router.post('/push')
async def gmail_push(request: Request) -> dict:
    '''Cloud Pub/Sub push endpoint for Gmail mailbox change notifications.

    Always acknowledges receipt (Pub/Sub redelivers on non-2xx). Cannot
    fetch or parse the actual message yet - that requires HERMES_GMAIL_*
    credentials, not yet configured. Once configured, this handler should
    call the Gmail API to fetch the new message(s) and pass each through
    normalize_gmail_message() -> process_channel_intake(), the same path
    /providers/email/webhook already uses for other email sources.
    '''
    body = await request.body()
    envelope = json.loads(body.decode('utf-8')) if body else {}
    parsed = parse_pubsub_push_envelope(envelope)

    status = gmail_provider_status()

    return {
        'acknowledged': True,
        'configured': status['configured'],
        'history_id': parsed.get('history_id'),
        'email_address': parsed.get('email_address'),
        'note': (
            'Notification received but not fetched - Gmail API credentials '
            'not configured. See HERMES_GMAIL_* in .env.example.'
            if not status['configured']
            else 'configured=True but the fetch-and-normalize path is not implemented yet'
        ),
    }
