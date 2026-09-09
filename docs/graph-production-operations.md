# Graph email and backfill operations

## Runtime guarantees

The Graph consumer keeps RabbitMQ I/O in the parent process and parses one
delivery in a spawned child. Prefetch is one. Heartbeats remain active during
parsing; processing has a 120-second deadline. Retry publication is confirmed
before the original delivery is acknowledged. HTTP 404/410 references are
preserved in the dead-letter queue; 429 retry delays respect Retry-After up to
one hour. Other transient failures retain the bounded retry schedule.

Intake database writes, including the transport dedupe key and draft, commit
together. A failed attempt rolls back so a broker redelivery can try again.
JSONL diagnostic events are not a transactional record; use database state
to determine whether an intake or backfill committed.

Taxonomy indexes refresh when the existing source caches reload. Literal
prefilters preserve matching semantics while avoiding absent-pattern compilation.

## Backfill API

Requires the existing drafts:publish permission. Submit a client-generated UUID
as job_id to POST /drafts/backfill/jobs. Reuse that UUID after an uncertain
HTTP result; changing parameters for an existing UUID returns 409.

```json
{
  "job_id": "CLIENT-GENERATED-UUID",
  "kind": "full-reparse",
  "dry_run": true,
  "batch_size": 10,
  "limit": 100
}
```

Kinds: full-reparse and signature-company-fill. Omit limit for the full
eligible snapshot. Creation returns 202 and captures the fixed draft-ID list.
GET /drafts/backfill/jobs lists recent jobs. GET /drafts/backfill/jobs/{job_id}
returns durable counts, status, last batch duration, and last error class.
POST /drafts/backfill/jobs/{job_id}/pause, /resume, or /cancel controls work.
Only one unfinished job is allowed. A pause/cancel prevents an in-flight batch
from committing if the control request wins the job-row lock; already committed
batches remain committed. Cancel does not revert completed work.

The dedicated worker processes bounded batches, using one transaction for
draft changes, field provenance, item outcomes, and progress. Parsing takes
place outside the write transaction. A worker crash before commit leaves the
batch pending. Updated or human-corrected drafts are skipped. Individual parser
failures become failed items; transaction failures pause the job for inspection.
Inspect draft_backfill_items for failed/skipped IDs. A new job can be submitted
after completion; it re-evaluates the eligible snapshot. Identical results do
not generate new provenance writes.

Legacy synchronous endpoints allow only bounded dry-run previews (maximum 20);
mutation calls return 409 directing callers to durable jobs.

## Health and recovery

Check the API /health, consumer and backfill Docker health status, RabbitMQ
ready/unacknowledged counts, dead-letter growth, and the Graph renewal timer.
The worker's last_batch_seconds is a completed-batch measurement, not a promise
that every email takes equal time. Normal email complexity still varies.

Do not blindly replay old dead letters. A 404 means the stored Graph reference
cannot currently be fetched; the email may have moved or been deleted. Preserve
the original queue until a separate mailbox reconciliation identifies recoverable
messages. No outbound email is required for these diagnostics.

## Deployment and rollback

Deploy the same image for hermes-api, hermes-graph-consumer, and
hermes-backfill-worker. Build-time tokenizer provisioning avoids first-request
downloads. The new schema is additive and compatible with the previous image.
Keep the previous image tags and a database backup before deployment.

For rollback, pause/cancel active backfills, stop the backfill worker, and
recreate API and consumer from their preserved previous images. Retain the
additive tables and committed draft corrections. Do not restore an entire old
database over mail received since deployment. Any selective data rollback must
be reviewed against the backup and concurrent reviewer edits.

## Verification

Run pytest and scripts/hermes-graph-heartbeat-check.py against disposable
infrastructure. The heartbeat check uses the host hermes-fix-test-rabbit and a
unique synthetic queue. Reliability database tests require the isolated host
hermes-fix-test-db or explicit HERMES_RELIABILITY_TEST_DB=1 for CI; never run them
against production. Write-inclusive snapshot benchmarks on 2026-09-09 completed
5/20/100 rows in 6.411/6.638/24.160 seconds, with every row updated and zero failures.
The first run includes process/cache warm-up.
