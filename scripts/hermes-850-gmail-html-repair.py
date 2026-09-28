"""Repair stored Gmail drafts whose body was ingested as raw HTML.

Fetches the original Gmail MIME body, applies the current deterministic
normalizer, and reparses affected drafts in bounded batches. Human-corrected
drafts are excluded. No LLM path is called.
"""
import json
import os
from copy import deepcopy
from datetime import datetime, timezone

from app.drafts.backfill import prepare_row
from app.email_parsing.provenance import CORRECTION_EXTRACTORS, record_field_provenance
from app.providers.gmail.service import fetch_gmail_messages, normalize_gmail_message
from app.runtime.db import cursor, transaction
from app.understanding.taxonomy.candidates import get_approved_boilerplate_lines


HTML_BODY_PATTERN = r'<(html|body|div|table|tbody|tr|td|span|p|br|style|script)(\s|>|/)'
REPAIR_VERSION = 'gmail_html_to_text_v1'


def _limit() -> int:
    try:
        value = int(os.getenv('HERMES_GMAIL_HTML_REPAIR_LIMIT', '2000'))
    except ValueError:
        value = 2000
    return min(max(value, 1), 10000)


def _affected_rows(limit: int) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """SELECT d.draft_id,d.source_message_id,d.payload,d.metadata,d.status,
                      d.draft_type,d.updated_at,d.confidence,d.requires_review
               FROM drafts d
               WHERE d.channel='email'
                 AND d.metadata->>'provider'='gmail'
                 AND d.status IN ('draft','needs_review')
                 AND COALESCE(d.metadata->>'gmail_html_repair_version','') <> %s
                 AND COALESCE(d.payload->>'text','') ~* %s
                 AND NOT EXISTS (
                     SELECT 1 FROM field_provenance fp
                     WHERE fp.parse_run_id=d.draft_id::text
                       AND fp.extractor=ANY(%s)
                 )
               ORDER BY d.created_at,d.draft_id LIMIT %s""",
            (REPAIR_VERSION, HTML_BODY_PATTERN, list(CORRECTION_EXTRACTORS), limit),
        )
        return list(cur.fetchall())


def main() -> None:
    rows = _affected_rows(_limit())
    messages = fetch_gmail_messages([str(row['source_message_id']) for row in rows])
    by_id = {str(message.get('id')): message for message in messages}
    boilerplate = get_approved_boilerplate_lines()
    prepared: list[tuple[dict, dict]] = []
    failures: list[dict[str, str]] = []

    for row in rows:
        source_id = str(row['source_message_id'])
        message = by_id.get(source_id)
        if not message:
            failures.append({'source_message_id': source_id, 'error': 'fetch_failed'})
            continue
        normalized = normalize_gmail_message(
            message,
            default_document_kind=os.getenv('HERMES_GMAIL_DEFAULT_DOCUMENT_KIND', 'job_description'),
        )
        repaired_row = dict(row)
        repaired_row['payload'] = deepcopy(row['payload'])
        repaired_row['payload']['text'] = normalized['text']
        result = prepare_row(repaired_row, 'review-reparse', boilerplate)
        if result is None:
            failures.append({'source_message_id': source_id, 'error': 'empty_normalized_body'})
            continue
        prepared.append((row, result))

    changed = 0
    moved_out_of_review = 0
    repaired_at = datetime.now(timezone.utc).isoformat()
    with transaction():
        with cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute("SET LOCAL statement_timeout='60s'")
            for row, result in prepared:
                cur.execute(
                    "SELECT updated_at,status FROM drafts WHERE draft_id=%s FOR UPDATE",
                    (row['draft_id'],),
                )
                current = cur.fetchone()
                if not current or current['updated_at'] != row['updated_at'] or current['status'] not in ('draft','needs_review'):
                    failures.append({'source_message_id': str(row['source_message_id']), 'error': 'concurrent_change'})
                    continue
                parsing = result['parsing']
                metadata_patch = json.dumps({
                    'gmail_html_repair_version': REPAIR_VERSION,
                    'gmail_html_repaired_at': repaired_at,
                })
                cur.execute(
                    """UPDATE drafts SET payload=%s,confidence=%s,requires_review=%s,
                              status=%s,metadata=metadata || %s::jsonb,updated_at=now()
                       WHERE draft_id=%s""",
                    (json.dumps(result['payload'], default=str), parsing.get('confidence', 0.0),
                     bool(parsing.get('requires_review')), result['status'], metadata_patch,
                     row['draft_id']),
                )
                record_field_provenance(str(row['draft_id']), result['entries'], transaction_cursor=cur)
                changed += int(result['changed'])
                moved_out_of_review += int(row['status'] == 'needs_review' and result['status'] == 'draft')

    print(json.dumps({
        'status': 'completed' if not failures else 'completed_with_failures',
        'selected_count': len(rows),
        'fetched_count': len(messages),
        'repaired_count': len(prepared) - sum(1 for item in failures if item['error'] == 'concurrent_change'),
        'changed_count': changed,
        'moved_out_of_review_count': moved_out_of_review,
        'failure_count': len(failures),
        'failures': failures[:20],
        'uses_llm': False,
    }, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
