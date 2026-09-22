#!/usr/bin/env python3
"""Queue a bounded deterministic reparse for new needs-review email drafts.

The durable backfill worker owns execution, batching, retries, audit state, and
restart recovery. This scheduler never invokes an LLM. Drafts already examined
with the current review-reparse version are excluded from future jobs.
"""
import os
from uuid import uuid4

from app.drafts.backfill import create_job
from app.drafts.review_rules import reconcile_review_status
from app.runtime.db import cursor, init_schema


def main() -> int:
    init_schema()
    reconciled = reconcile_review_status(dry_run=False, limit=500)
    print(f"ready_status_reconciled={reconciled['resolved_count']}")

    with cursor() as cur:
        cur.execute("SELECT job_id,status FROM draft_backfill_jobs "
                    "WHERE status IN ('queued','running','paused') ORDER BY created_at LIMIT 1")
        existing = cur.fetchone()
    if existing:
        print(f"review_reparse_not_queued active_job={existing['job_id']} status={existing['status']}")
        return 0

    limit = int(os.getenv('HERMES_DAILY_REVIEW_REPARSE_LIMIT', '2000'))
    job = create_job(uuid4(), 'review-reparse', dry_run=False, batch_size=100, limit=limit)
    print(f"review_reparse_job={job['job_id']} status={job['status']} total={job['total_count']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
