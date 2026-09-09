#!/usr/bin/env python3
"""Single supervised worker; advisory lock prevents concurrent workers."""
import logging
import signal
import time
from pathlib import Path

from app.runtime.db import cursor, get_pool, init_schema
from app.drafts.backfill import run_batch

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
stopping = False


def stop(_signum, _frame):
    global stopping
    stopping = True


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_schema()
    with get_pool().connection() as lock_connection:
        lock_connection.autocommit = True
        acquired = lock_connection.execute('SELECT pg_try_advisory_lock(892310481)').fetchone()[0]
        if not acquired:
            raise RuntimeError('Another backfill worker owns the processing lock')
        try:
            while not stopping:
                Path('/tmp/hermes-backfill-heartbeat').touch()
                with cursor() as cur:
                    cur.execute("SELECT job_id FROM draft_backfill_jobs WHERE status IN ('queued','running') ORDER BY created_at LIMIT 1")
                    job = cur.fetchone()
                if not job:
                    time.sleep(2)
                    continue
                try:
                    run_batch(job['job_id'])
                    logging.info('Backfill batch committed job_id=%s', job['job_id'])
                except Exception as exc:
                    logging.error('Backfill paused job_id=%s error=%s', job['job_id'], type(exc).__name__)
                    with cursor() as cur:
                        cur.execute("UPDATE draft_backfill_jobs SET status='paused',last_error=%s,updated_at=now() WHERE job_id=%s AND status IN ('queued','running')",
                                    (type(exc).__name__, job['job_id']))
                time.sleep(0.25)
        finally:
            lock_connection.execute('SELECT pg_advisory_unlock(892310481)')


if __name__ == '__main__':
    main()
