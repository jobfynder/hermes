"""Recover recent Gmail intake without relying on a workstation or Pub/Sub.

Run from a systemd timer. The Gmail query is a bounded look-back window;
intake_log provides the durable cursor, and the normal channel intake path
provides transport and exact-content deduplication.
"""
import json
import os

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.gmail.service import (
    fetch_gmail_messages,
    gmail_provider_status,
    list_gmail_message_ids,
    normalize_gmail_message,
)
from app.runtime.db import cursor


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(1, value), maximum)


def _already_recorded(message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    with cursor() as cur:
        cur.execute(
            "SELECT DISTINCT source_message_id FROM intake_log "
            "WHERE channel='email' AND source_message_id=ANY(%s)",
            (message_ids,),
        )
        return {str(row['source_message_id']) for row in cur.fetchall()}


def main() -> None:
    if not gmail_provider_status()['configured']:
        raise SystemExit('Gmail reconciliation is not configured')

    query = os.getenv(
        'HERMES_GMAIL_RECONCILE_QUERY', 'label:nvoids newer_than:2d'
    ).strip()
    scan_limit = _positive_int('HERMES_GMAIL_RECONCILE_SCAN_LIMIT', 10000, 50000)
    batch_size = _positive_int('HERMES_GMAIL_RECONCILE_BATCH_SIZE', 500, 2000)
    default_kind = os.getenv(
        'HERMES_GMAIL_DEFAULT_DOCUMENT_KIND', 'job_description'
    ).strip().lower()

    # Gmail lists newest first. Reverse the unseen set so an outage backlog is
    # drained oldest first instead of continually chasing new arrivals.
    listed = list_gmail_message_ids(query, max_results=scan_limit)
    recorded = _already_recorded(listed)
    pending = [message_id for message_id in reversed(listed) if message_id not in recorded]
    selected = pending[:batch_size]

    counts: dict[str, int] = {}
    failures: list[dict[str, str]] = []
    fetched = fetch_gmail_messages(selected)
    fetched_ids = {str(message.get('id')) for message in fetched}
    for missing_id in selected:
        if missing_id not in fetched_ids:
            failures.append({'source_message_id': missing_id, 'error': 'fetch_failed'})

    for message in fetched:
        source_message_id = str(message.get('id') or 'unknown')
        try:
            normalized = normalize_gmail_message(
                message, default_document_kind=default_kind
            )
            result = process_channel_intake(ChannelIntakeRequest(**normalized))
            counts[result.intake_status] = counts.get(result.intake_status, 0) + 1
        except Exception as exc:
            failures.append({
                'source_message_id': source_message_id,
                'error': type(exc).__name__,
            })

    print(json.dumps({
        'status': 'completed' if not failures else 'completed_with_failures',
        'query': query,
        'listed_count': len(listed),
        'already_recorded_count': len(recorded),
        'pending_count': len(pending),
        'selected_count': len(selected),
        'fetched_count': len(fetched),
        'outcomes': counts,
        'failure_count': len(failures),
        'failures': failures[:20],
    }, sort_keys=True))

    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
