"""Durable, bounded backfills. No parsing or network work inside write transactions."""
from copy import deepcopy
import json
import time
import signal
import threading
from uuid import UUID
from pathlib import Path

from app.runtime.db import cursor
from app.email_parsing.parsers import apply_signature_company_fill, parse_email_business_records
from app.email_parsing.signature import parse_email_signature
from app.email_parsing.signature_learning import apply_learned_signature_patterns
from app.email_parsing.provenance import (
    CORRECTION_EXTRACTORS, build_email_parsing_provenance,
    build_signature_provenance, record_field_provenance,
)
from app.understanding.taxonomy.candidates import get_approved_boilerplate_lines


def get_job(job_id):
    with cursor() as cur:
        cur.execute("SELECT * FROM draft_backfill_jobs WHERE job_id=%s", (UUID(str(job_id)),))
        return cur.fetchone()


def create_job(job_id, kind, dry_run=True, batch_size=10, limit=None):
    job_id = UUID(str(job_id))
    if kind not in ('full-reparse', 'review-reparse', 'signature-company-fill') or not 1 <= batch_size <= 100:
        raise ValueError('Invalid backfill kind or batch size')
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    with cursor() as cur:
        # Serializes creation so overlapping requests cannot create competing
        # mutation jobs. Repeating the same UUID returns the existing job.
        cur.execute('SELECT pg_advisory_xact_lock(892310480)')
        cur.execute('SELECT * FROM draft_backfill_jobs WHERE job_id=%s', (job_id,))
        existing = cur.fetchone()
        if existing:
            if (existing['kind'], existing['dry_run'], existing['batch_size'], existing['item_limit']) != (kind, dry_run, batch_size, limit):
                raise ValueError('Job ID already exists with different parameters')
            return existing
        cur.execute("SELECT job_id FROM draft_backfill_jobs WHERE status IN ('queued','running','paused') LIMIT 1")
        if cur.fetchone():
            raise ValueError('An unfinished backfill already exists; resume or cancel it first')
        cur.execute('INSERT INTO draft_backfill_jobs(job_id,kind,dry_run,batch_size,item_limit) VALUES (%s,%s,%s,%s,%s)',
                    (job_id, kind, dry_run, batch_size, limit))
        cur.execute('''INSERT INTO draft_backfill_items(job_id,draft_id)
            SELECT %s, d.draft_id FROM drafts d
            WHERE d.draft_type='draft_job_requirement' AND d.status IN ('draft','needs_review')
            AND (%s <> 'review-reparse' OR d.status='needs_review')
            AND NOT EXISTS (SELECT 1 FROM field_provenance fp
                WHERE fp.parse_run_id=d.draft_id::text AND fp.extractor=ANY(%s))
            ORDER BY d.created_at,d.draft_id LIMIT %s''', (job_id, kind, list(CORRECTION_EXTRACTORS), limit))
        total = cur.rowcount
        cur.execute("UPDATE draft_backfill_jobs SET total_count=%s,status=%s WHERE job_id=%s RETURNING *",
                    (total, 'queued' if total else 'completed', job_id))
        return cur.fetchone()


def control_job(job_id, action):
    transitions = {'pause': ('paused', ('queued','running')),
                   'resume': ('queued', ('paused',)),
                   'cancel': ('cancelled', ('queued','running','paused'))}
    if action not in transitions:
        raise ValueError('Unknown job action')
    target, allowed = transitions[action]
    with cursor() as cur:
        cur.execute('UPDATE draft_backfill_jobs SET status=%s,updated_at=now() WHERE job_id=%s AND status=ANY(%s) RETURNING *',
                    (target, UUID(str(job_id)), list(allowed)))
        return cur.fetchone()


def prepare_row(row, kind, boilerplate):
    payload = deepcopy(row['payload'])
    structured = payload.get('structured_data') or {}
    old_parsing = structured.get('email_parsing') or {}
    old_signature = structured.get('signature') or {}
    if kind in ('full-reparse', 'review-reparse'):
        text = payload.get('text') or ''
        if not text.strip():
            return None
        sender = ((row.get('metadata') or {}).get('sender') or {}).get('email')
        parsing = parse_email_business_records(text, 'job_description', boilerplate)
        signature = parse_email_signature(text=text, sender_email=sender)
        domain = sender.rsplit('@', 1)[-1].lower() if sender and '@' in sender else None
        apply_learned_signature_patterns(signature.get('contact', {}), domain)
        parsing, _ = apply_signature_company_fill(parsing, signature)
    else:
        if not old_parsing.get('records'):
            return None
        parsing, _ = apply_signature_company_fill(deepcopy(old_parsing), old_signature)
        signature = old_signature
    status = 'needs_review' if parsing.get('requires_review') else 'draft'
    changed = (parsing != old_parsing or signature != old_signature or
               row['status'] != status or row['confidence'] != parsing.get('confidence', 0.0) or
               row['requires_review'] != bool(parsing.get('requires_review')))
    structured.update(email_parsing=parsing, signature=signature)
    payload['structured_data'] = structured
    entries = build_email_parsing_provenance(parsing)
    if signature.get('detected'):
        entries += build_signature_provenance(signature)
    return {'payload': payload, 'parsing': parsing, 'entries': entries,
            'status': status, 'changed': changed}


def run_batch(job_id):
    """Called only by the single advisory-lock-owning worker.

    If interrupted before commit all items remain pending. Concurrent draft
    edits are skipped via updated_at and correction checks under row locks.
    Item outcomes are the transactional audit trail, including dry-run results.
    """
    started = time.monotonic()
    with cursor() as cur:
        cur.execute("UPDATE draft_backfill_jobs SET status='running',updated_at=now(),last_error=NULL WHERE job_id=%s AND status IN ('queued','running') RETURNING *", (job_id,))
        job = cur.fetchone()
        if not job:
            return False
        cur.execute('''SELECT i.draft_id,d.payload,d.metadata,d.status,d.updated_at,d.confidence,d.requires_review
            FROM draft_backfill_items i LEFT JOIN drafts d ON d.draft_id=i.draft_id
            WHERE i.job_id=%s AND i.status='pending' ORDER BY i.draft_id LIMIT %s''', (job_id, job['batch_size']))
        rows = cur.fetchall()
    boilerplate = get_approved_boilerplate_lines()
    prepared = []
    for row in rows:
        Path('/tmp/hermes-backfill-heartbeat').touch()
        try:
            def timed_out(_signum, _frame):
                raise TimeoutError('Draft exceeded processing deadline')
            timed = threading.current_thread() is threading.main_thread() and hasattr(signal, 'SIGALRM')
            if timed:
                previous_handler = signal.signal(signal.SIGALRM, timed_out)
                signal.alarm(120)
            result = prepare_row(row, job['kind'], boilerplate) if row['status'] in ('draft','needs_review') else None
            prepared.append((row, result, None))
        except Exception as exc:
            # Error class only: exception messages may contain email content.
            prepared.append((row, None, type(exc).__name__))
        finally:
            if timed:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous_handler)
    counts = {'changed': 0, 'skipped': 0, 'failed': 0}
    with cursor() as cur:
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SET LOCAL statement_timeout='30s'")
        cur.execute('SELECT status FROM draft_backfill_jobs WHERE job_id=%s FOR UPDATE', (job_id,))
        if cur.fetchone()['status'] != 'running':
            return False
        for row, result, error in prepared:
            outcome = 'failed' if error else 'skipped' if result is None else 'unchanged'
            if result is not None:
                cur.execute('''SELECT d.updated_at,d.status,d.draft_type,
                    EXISTS(SELECT 1 FROM field_provenance fp WHERE fp.parse_run_id=d.draft_id::text AND fp.extractor=ANY(%s)) AS corrected
                    FROM drafts d WHERE d.draft_id=%s FOR UPDATE''', (list(CORRECTION_EXTRACTORS), row['draft_id']))
                current = cur.fetchone()
                if (not current or current['updated_at'] != row['updated_at'] or current['corrected'] or
                    current['draft_type'] != 'draft_job_requirement' or current['status'] not in ('draft','needs_review')):
                    outcome = 'skipped'
                elif result['changed']:
                    outcome = 'changed'
                    if not job['dry_run']:
                        parsing = result['parsing']
                        cur.execute('''UPDATE drafts SET payload=%s,confidence=%s,requires_review=%s,status=%s,updated_at=now()
                            WHERE draft_id=%s''', (json.dumps(result['payload'], default=str), parsing.get('confidence', 0.0),
                            bool(parsing.get('requires_review')), result['status'], row['draft_id']))
                        record_field_provenance(str(row['draft_id']), result['entries'], transaction_cursor=cur)
            if outcome in counts:
                counts[outcome] += 1
            cur.execute('UPDATE draft_backfill_items SET status=%s,error=%s WHERE job_id=%s AND draft_id=%s',
                        (outcome, error, job_id, row['draft_id']))
        processed = job['processed_count'] + len(rows)
        status = ('completed_with_errors' if job['failed_count'] + counts['failed'] else 'completed') if processed >= job['total_count'] else 'running'
        cur.execute('''UPDATE draft_backfill_jobs SET processed_count=processed_count+%s,changed_count=changed_count+%s,
            skipped_count=skipped_count+%s,failed_count=failed_count+%s,status=%s,updated_at=now(),last_batch_seconds=%s WHERE job_id=%s''',
            (len(rows),counts['changed'],counts['skipped'],counts['failed'],status,time.monotonic()-started,job_id))
    return True
