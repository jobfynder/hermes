'''Keeps the Microsoft Graph mailbox subscription(s) alive.

Run this on a recurring schedule -- e.g. a daily host cron entry:

    0 6 * * * docker exec hermes-api python scripts/hermes-850-graph-subscription-renew.py >> /var/log/hermes-graph-renew.log 2>&1

Graph's own documented max subscription lifetime for Outlook mail
resources is ~2.94 days, so running this less often than daily risks a
gap where notifications silently stop arriving until the next run
re-creates the subscription. Idempotent: creates any missing
subscription, renews any expiring within 24h, leaves already-fresh ones
alone. Requires HERMES_MS_GRAPH_CLIENT_ID/SECRET/TENANT_ID,
HERMES_MS_GRAPH_MAILBOXES, HERMES_MS_GRAPH_CLIENT_STATE, and
HERMES_PUBLIC_WEBHOOK_BASE_URL all set -- see .env.example.
'''
from app.providers.microsoft_graph.service import sync_graph_subscriptions


def run() -> None:
    result = sync_graph_subscriptions()
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
