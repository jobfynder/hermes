import json

from fastapi import APIRouter, Request, Response

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.microsoft_graph.service import (
    fetch_graph_message,
    microsoft_graph_provider_status,
    normalize_graph_message,
)

router = APIRouter(prefix='/providers/microsoft-graph', tags=['Microsoft Graph Provider'])


@router.get('/status')
def microsoft_graph_status() -> dict:
    return microsoft_graph_provider_status()


@router.post('/webhook')
async def microsoft_graph_webhook(request: Request) -> Response:
    '''Microsoft Graph change-notification webhook.

    Subscription validation handshake: when a subscription is created or
    renewed, Graph sends a POST with ?validationToken=<token> and expects
    the raw token echoed back as text/plain within 10 seconds. This must
    happen before any auth/signature check, per Graph's own contract -
    Graph will not create the subscription otherwise.

    Actual change notifications carry a `resource` reference per item in
    `value[]`; each is fetched via fetch_graph_message() (app-only Graph
    auth) and, if the fetch succeeds, normalized and passed through the
    same process_channel_intake() pipeline every other email source uses.
    A notification whose fetch fails (or when Graph credentials aren't
    configured) is simply skipped -- still acknowledged, so Graph doesn't
    retry a fetch that will fail again for the same reason.
    '''
    validation_token = request.query_params.get('validationToken')

    if validation_token is not None:
        return Response(content=validation_token, media_type='text/plain')

    body = await request.body()
    envelope = json.loads(body.decode('utf-8')) if body else {}
    notifications = envelope.get('value', [])

    status = microsoft_graph_provider_status()

    processed: list[dict] = []
    if status['configured']:
        for notification in notifications:
            message = fetch_graph_message(notification.get('resource'))
            if not message:
                continue

            normalized = normalize_graph_message(message)
            channel_request = ChannelIntakeRequest(**normalized)
            result = process_channel_intake(channel_request)
            processed.append({
                'source_message_id': result.source_message_id,
                'intake_status': result.intake_status,
                'document_kind': result.document_kind,
                'draft_object_type': result.draft_object_type,
            })

    return Response(
        content=json.dumps({
            'acknowledged': True,
            'configured': status['configured'],
            'notification_count': len(notifications),
            'processed_count': len(processed),
            'processed': processed,
            'note': (
                'Notifications received but not fetched - Microsoft Graph '
                'credentials not configured. See HERMES_MS_GRAPH_* in '
                '.env.example.'
                if not status['configured']
                else None
            ),
        }),
        media_type='application/json',
    )
