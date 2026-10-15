from app.security.rbac import require_admin_permission
import json

from fastapi import APIRouter, Request, Depends, HTTPException

from app import config
from app.security.google_push import PushIdentity, require_google_push

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
def gmail_status(_principal: dict = Depends(require_admin_permission("runtime:read"))) -> dict:
    return gmail_provider_status()


def gmail_push_identity(request: Request) -> dict:
    """Reject disabled or incomplete configuration before any body read."""
    if not config.HERMES_GMAIL_PUSH_ENABLED:
        raise HTTPException(status_code=410, detail="Gmail push ingestion is disabled")
    project = config.HERMES_GMAIL_PUSH_PROJECT_ID
    subscription = config.HERMES_GMAIL_PUSH_SUBSCRIPTION
    prefix = f"projects/{project}/subscriptions/"
    try:
        if (not project or project != project.strip() or "/" in project
                or not subscription.startswith(prefix)
                or not subscription[len(prefix):]
                or "/" in subscription[len(prefix):]
                or subscription != subscription.strip()):
            raise ValueError("Incomplete push configuration")
        identity = PushIdentity(config.HERMES_GMAIL_PUSH_AUDIENCE,
                                config.HERMES_GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL)
    except ValueError:
        raise HTTPException(status_code=503, detail="Gmail push ingestion is unavailable") from None
    return require_google_push(identity)(request)


@router.post('/push')
async def gmail_push(request: Request, _principal: dict = Depends(gmail_push_identity)) -> dict:
    """Unused by production. Future enabled delivery requires verified Google OIDC."""
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
