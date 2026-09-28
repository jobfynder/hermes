"""Move old nvoids-labeled Gmail messages to Trash, keeping today's mail.

The Gmail query uses an epoch-second cutoff for the start of today in the
configured timezone, avoiding Gmail's date-string/Pacific-time behavior.
Deletion is reversible in Gmail Trash and requires explicit enablement plus
the gmail.modify OAuth scope.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.providers.gmail.service import list_gmail_message_ids, trash_gmail_messages
from app.runtime.db import cursor


def _enabled(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}


def _safely_processed(message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    with cursor() as cur:
        cur.execute(
            """SELECT DISTINCT source_message_id FROM intake_log
               WHERE channel='email' AND source_message_id=ANY(%s)
                 AND status IN ('parsed','blocked')""",
            (message_ids,),
        )
        return {str(row['source_message_id']) for row in cur.fetchall()}


def main() -> None:
    if not _enabled('HERMES_GMAIL_CLEANUP_ENABLED'):
        raise SystemExit('Gmail cleanup is disabled')

    timezone_name = os.getenv('HERMES_GMAIL_CLEANUP_TIMEZONE', 'America/New_York')
    timezone = ZoneInfo(timezone_name)
    now = datetime.now(timezone)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_epoch = int(today_start.timestamp())
    limit = min(max(int(os.getenv('HERMES_GMAIL_CLEANUP_LIMIT', '50000')), 1), 50000)
    query = f'label:nvoids -in:trash before:{cutoff_epoch}'
    message_ids = list_gmail_message_ids(query, max_results=limit)
    processed = _safely_processed(message_ids)
    eligible_ids = [message_id for message_id in message_ids if message_id in processed]
    dry_run = _enabled('HERMES_GMAIL_CLEANUP_DRY_RUN', 'true')

    moved, failures = (0, []) if dry_run else trash_gmail_messages(eligible_ids)
    print(json.dumps({
        'status': 'dry_run' if dry_run else ('completed' if not failures else 'completed_with_failures'),
        'timezone': timezone_name,
        'cutoff': today_start.isoformat(),
        'query': query,
        'matched_count': len(message_ids),
        'eligible_processed_count': len(eligible_ids),
        'preserved_unprocessed_count': len(message_ids) - len(eligible_ids),
        'moved_to_trash_count': moved,
        'failure_count': len(failures),
        'failed_message_ids': failures[:20],
    }, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
