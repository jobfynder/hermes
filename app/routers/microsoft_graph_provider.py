import json

from fastapi import APIRouter, Request, Response

from app.providers.microsoft_graph.service import microsoft_graph_provider_status

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

    Actual change notifications only carry a resource reference (message
    ID), not the message body - fetching the message requires an
    authenticated Graph client (HERMES_MS_GRAPH_* credentials), not yet
    configured.
    '''
    validation_token = request.query_params.get('validationToken')

    if validation_token is not None:
        return Response(content=validation_token, media_type='text/plain')

    body = await request.body()
    envelope = json.loads(body.decode('utf-8')) if body else {}
    notifications = envelope.get('value', [])

    status = microsoft_graph_provider_status()

    return Response(
        content=json.dumps({
            'acknowledged': True,
            'configured': status['configured'],
            'notification_count': len(notifications),
            'note': (
                'Notifications received but not fetched - Microsoft Graph '
                'credentials not configured. See HERMES_MS_GRAPH_* in '
                '.env.example.'
                if not status['configured']
                else 'configured=True but the fetch-and-normalize path is not implemented yet'
            ),
        }),
        media_type='application/json',
    )
