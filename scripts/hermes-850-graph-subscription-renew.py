'''Keeps the Microsoft Graph mailbox subscription(s) alive.

Run this from the 12-hour ``hermes-graph-renew.timer`` installed by
jobfynder-infra. Graph's documented maximum subscription lifetime for
Outlook messages is under seven days. Idempotent: creates any missing
subscription, renews any expiring within 24h, leaves already-fresh ones
alone. Requires HERMES_MS_GRAPH_CLIENT_ID/SECRET/TENANT_ID,
HERMES_MS_GRAPH_MAILBOXES, HERMES_MS_GRAPH_CLIENT_STATE, and
HERMES_PUBLIC_WEBHOOK_BASE_URL all set -- see .env.example.
'''
from app.providers.microsoft_graph.service import sync_graph_subscriptions


def run() -> None:
    result = sync_graph_subscriptions()
    # The result contains identifiers and status only. Never print the
    # process environment, access token, client secret, or clientState.
    print(result)

    if result.get('status') == 'blocked':
        raise SystemExit(f"Graph subscription sync blocked: {result.get('reason')}")

    failures = {
        mailbox: info
        for mailbox, info in result.get('mailboxes', {}).items()
        if info.get('status') == 'failed'
    }
    if failures:
        raise SystemExit(f'Graph subscription sync had failures: {failures}')


if __name__ == '__main__':
    run()
