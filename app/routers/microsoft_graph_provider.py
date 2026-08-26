import json
import logging
import os

from fastapi import APIRouter, Depends, Request, Response

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.microsoft_graph.service import (
    fetch_graph_message,
    list_stored_subscriptions,
    microsoft_graph_provider_status,
    normalize_graph_message,
    sync_graph_subscriptions,
    verify_notification_client_state,
)
from app.security.rbac import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/providers/microsoft-graph', tags=['Microsoft Graph Provider'])

# Kill switch for the OLD synchronous webhook path below, now that Graph
# notifications are meant to arrive via jobfynder-infra's COMM gateway
# (hooks.jobfynder.com/microsoft-graph/mail -> RabbitMQ ->
# scripts/hermes-850-graph-notification-consumer.py) instead of calling
# this route directly. Defaults to "still enabled" on purpose -- flipping
# it off is only safe once patch-hermes-graph-subscription.py has been run
# (so Graph is actually registered against the new URL, not this one) and
# the new consumer is confirmed processing mail. Until both of those are
# true, this route may still be the one Graph is actually calling.
#
# Once confirmed, set HERMES_MS_GRAPH_LEGACY_WEBHOOK_ENABLED=false. Leaving
# this route silently live and reachable after the migration is a second,
# forgotten front door into Hermes's Mail.Read-scoped fetch-and-parse path,
# defended by nothing but clientState.
_LEGACY_WEBHOOK_DISABLED_VALUES = {"0", "false", "no", "off", "disabled"}
LEGACY_WEBHOOK_ENABLED = (
    os.getenv("HERMES_MS_GRAPH_LEGACY_WEBHOOK_ENABLED", "true").strip().lower()
    not in _LEGACY_WEBHOOK_DISABLED_VALUES
)


@router.get('/status')
def microsoft_graph_status() -> dict:
    return microsoft_graph_provider_status()


@router.get('/subscriptions')
def list_subscriptions(
    _user: dict = Depends(require_permission('providers:manage')),
) -> dict:
    return {'mailboxes': list_stored_subscriptions()}


@router.post('/subscriptions/sync')
def sync_subscriptions(
    _user: dict = Depends(require_permission('providers:manage')),
) -> dict:
    '''Creates or renews the Graph change-notification subscription for
    every mailbox in HERMES_MS_GRAPH_MAILBOXES. Required operational
    infrastructure, not a one-time setup step -- Graph subscriptions for
    mail expire after up to 7 days, so this must be called on a recurring
    schedule (see scripts/hermes-850-graph-subscription-renew.py, meant to
    run from a daily host cron) or notifications silently stop arriving.
    '''
    return sync_graph_subscriptions()


@router.post('/webhook')
async def microsoft_graph_webhook(request: Request) -> Response:
    '''Microsoft Graph change-notification webhook -- LEGACY PATH.

    This is the original synchronous implementation: fetch and parse
    happen inline, in the same request Graph is waiting on. The current
    architecture moves that off this route entirely -- see
    LEGACY_WEBHOOK_ENABLED above. This handler is kept working (not
    deleted) so it still exists as a fallback and so its logic remains the
    reference implementation scripts/hermes-850-graph-notification-
    consumer.py's queue-based version was built to match, but it should
    not be the route Graph actually calls once the migration is complete.

    Subscription validation handshake: when a subscription is created or
    renewed, Graph sends a POST with ?validationToken=<token> and expects
    the raw token echoed back as text/plain within 10 seconds. This must
    happen before any auth/signature check, per Graph's own contract -
    Graph will not create the subscription otherwise. Answered
    unconditionally, even while the legacy path is disabled below, since a
    stale subscription still pointed here could otherwise wedge a renewal.

    Actual change notifications carry a `resource` reference and a
    `clientState` per item in `value[]`. Each notification's clientState
    is checked against HERMES_MS_GRAPH_CLIENT_STATE
    (verify_notification_client_state) before anything is fetched --
    this endpoint is necessarily unauthenticated (Graph calls it directly,
    no bearer token), so clientState is the only defense against a forged
    notification making Hermes fetch and ingest an attacker-chosen
    message using this app's own Mail.Read grant. A notification that
    fails this check, or whose message fetch fails, is skipped -- still
    acknowledged, so Graph doesn't retry a fetch that will fail again for
    the same reason.
    '''
    validation_token = request.query_params.get('validationToken')

    if validation_token is not None:
        return Response(content=validation_token, media_type='text/plain')

    if not LEGACY_WEBHOOK_ENABLED:
        logger.warning(
            "Received a Microsoft Graph notification on the legacy "
            "synchronous webhook route (/providers/microsoft-graph/webhook) "
            "while HERMES_MS_GRAPH_LEGACY_WEBHOOK_ENABLED is disabled. "
            "Nothing should be calling this route once subscriptions point "
            "at hooks.jobfynder.com/microsoft-graph/mail -- if this keeps "
            "happening, something (a stale subscription, DNS, cached "
            "config) still points here and needs to be found."
        )
        return Response(
            status_code=410,
            content=json.dumps({
                'acknowledged': False,
                'reason': 'legacy_webhook_disabled',
            }),
            media_type='application/json',
        )

    body = await request.body()
    envelope = json.loads(body.decode('utf-8')) if body else {}
    notifications = envelope.get('value', [])

    status = microsoft_graph_provider_status()

    processed: list[dict] = []
    rejected_count = 0
    if status['configured']:
        for notification in notifications:
            if not verify_notification_client_state(notification):
                rejected_count += 1
                continue

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
            'rejected_count': rejected_count,
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
