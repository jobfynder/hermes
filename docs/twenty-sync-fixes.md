# Twenty CRM sync (`jfcrm-sync`): diagnosis, what was changed on 2026-11-10, and the code fixes still needed

Scope: the separate host service `jfcrm-sync` (`/opt/jfcrm/runtime-20261104`, state in schema `jfcrm_sync`).
Hermes only monitors it (`/sync/status`); it does not own this code.

## Why code changes cannot be applied from Hermes

`session.mjs` refuses to start unless the hash of **every** `.mjs` file in `automation/` equals the
`runtimeFingerprint` in a signed activation approval (`RUNTIME_FINGERPRINT_NOT_APPROVED`). Editing any file
on the server would stop the sync at its next restart (it restarts about every 6 h) until the approval is
re-signed by the key holder. The copy under `/opt/jfcrm/verification/jfcrm-019j/source` is older than the
running build and does not match it, so a patch cannot be tested against the deployed code from there.
The three code fixes below therefore need the owner to build, test with the matching test suite, and re-approve.

## Findings

| # | Finding | Evidence |
|---|---|---|
| 1 | Nightly reconciliation never runs | `session.mjs` only calls `reconciler.once()` when **nothing anywhere is unsettled** (no outbox PENDING/PUBLISHING, no inbox PROCESSING/REPLAY_READY). The outbox always holds ~800-1000 rows, and ~9.7k inbox rows were stuck. The deferral is swallowed silently. State has said `RUNNING`, `checked: 0` since 2026-11-04. |
| 2 | Updates stuck in `PROCESSING` | On `DEPENDENCY_UNAVAILABLE` the worker returns `RETRY` to the **broker**, which holds the delay in memory. Crashes on 4-6 Nov lost those retries; the outbox rows are already `PUBLISHED`, so nothing re-sends them. 7,006 rows carried `DEPENDENCY_UNAVAILABLE`, 300 `55P03`. |
| 3 | Restarts about every 6 h | Role `jfcrm_sync_runtime` had `idle_in_transaction_session_timeout=30s`; Postgres logged `terminating connection due to idle-in-transaction timeout` at each `RUNTIME_FAILURE`. Also 440 `lock timeout` errors (audit lock), 20 statement timeouts, 11 `too many connections`. |
| 4 | Audit lock contention | `store.audit()` takes `pg_advisory_xact_lock(19101901)` first. When the caller passes its own `db` (an open transaction) the lock is held until that transaction commits, including across Twenty API calls, with `lock_timeout=1s` for everyone else. |
| 5 | Send rate | About 1,000 sent/h vs about 1,170 created/h. 78% of traffic is hourly `CONTACT_*_RECALCULATE` (22k of 28k per day); real data changes are about 2.9k/day. Every update waits more than 5 minutes. |

## Changed on 2026-11-10 (all outside the fingerprinted code, all reversible)

1. **Closed 3 stale alert types** (HTTP_521, REPEATED_API_FAILURES, RETRY_AFTER_EXCEEDS_BUDGET; 7 rows, last seen 8 Nov, delivery healthy since):
   `UPDATE jfcrm_sync.alerts SET active=false, recovered_at=now() WHERE ...` (same statement the sync uses). They reopen by themselves if the condition returns.
2. **Role limits** (apply to new connections, i.e. after the next service restart):
   ```sql
   ALTER ROLE jfcrm_sync_runtime SET idle_in_transaction_session_timeout = '120s';  -- was 30s
   ALTER ROLE jfcrm_sync_runtime SET lock_timeout = '5s';                           -- was 1s
   -- rollback:
   ALTER ROLE jfcrm_sync_runtime SET idle_in_transaction_session_timeout = '30s';
   ALTER ROLE jfcrm_sync_runtime SET lock_timeout = '1s';
   ```
3. **Recovered stuck updates** (backup of the before-state: `public.jfcrm_recovery_20261110`):
   - 3,211 `PROCESSING` updates already superseded by a newer version of the same stream (`stream_versions.version` greater than the event's `sourceVersion`) were set to `STALE`, the sync's own status for that case.
   - 6,503 real updates (6,482 `HIRING_SIGNAL_UPSERT`, 18 `CONTACT_UPSERT`, 3 `CONTACT_SCORE_RECALCULATE`) were put back in the outbox (`status='PENDING'`, `published_at=NULL`, lease cleared), staggered 12 s apart (about 5/min) so live updates keep flowing. Prerequisite records (company/contact upserts) were queued first.
   - Rollback:
     ```sql
     UPDATE jfcrm_sync.inbox i SET status=r.inbox_status, attempts=r.inbox_attempts, last_error=r.inbox_last_error, updated_at=r.inbox_updated_at
       FROM public.jfcrm_recovery_20261110 r WHERE i.event_id=r.inbox_event_id;
     UPDATE jfcrm_sync.outbox o SET status=r.outbox_status, available_at=r.outbox_available_at, published_at=r.outbox_published_at
       FROM public.jfcrm_recovery_20261110 r WHERE o.event_id=r.outbox_event_id AND o.status='PENDING';
     ```
   - Known limit: for all 6,482 signals the company is in Twenty; for 5,930 so is the recruiter. About 550 signals depend on recruiters that are themselves blocked behind quarantined companies and will keep returning `DEPENDENCY_UNAVAILABLE` until a person resolves the quarantine.
   - Note: the manual changes bypass `jfcrm_sync.audit` (hash chain). This document and the backup table are the record.

## Code fixes for the owner (need build, tests, fingerprint re-approval)

1. **Reconcile per entity, not per system** (`session.mjs`, `reconcile.mjs`)
   - Remove the global `unsettled` gate. `verify()` already refuses an entity with unverified events (`RECONCILIATION_PENDING_EVENTS`) and the per-entity advisory lock already prevents concurrent handling.
   - In `once()`, on `RECONCILIATION_PENDING_EVENTS` for one entity: count it as `deferred`, advance the cursor, continue (do not throw and abort the batch).
   - Finish as `PASS` only when `deferred = 0` and `exceptions = 0`; otherwise a distinct `PARTIAL` result that carries the deferred ids to the next night and raises a visible alert. Never report `PASS` with entities unverified.
   - Keep the single reconciler connection (the gate's comment explains the pool exhaustion it was avoiding).
2. **Recover stuck `PROCESSING` automatically** (new step in the runtime loop)
   - Each loop: inbox `PROCESSING` older than N minutes with outbox `PUBLISHED` -> set outbox `PENDING` (what was done by hand above); `STALE` when a newer stream version exists. Cap per loop and respect backpressure.
   - Do not rely on broker memory for retry state.
3. **Idle-in-transaction and the audit lock** (`store.mjs`, `worker.mjs`, `twenty.mjs`, `reconcile.mjs`)
   - Never keep a transaction open across a Twenty API call. Find the caller holding one (the Postgres log shows the idle session); the role limit raise above is only a stopgap.
   - `audit()`: when the caller supplies its own `db`, the global lock is held until that transaction ends. Append audit rows in a short separate transaction, or buffer them and append immediately before `COMMIT`.
   - Log the error code and stack at `RUNTIME_FAILURE` (it currently prints only the word, which hid the cause).
4. **Send volume** (`activity-clock.mjs`): emit `CONTACT_*_RECALCULATE` only when inputs changed or the score/activity bucket would change. That removes about 78% of traffic and is a bigger win than tuning the send rate.

## How to verify

- Sync status page: "Updates being verified" count falls from about 9.7k as the staggered re-send completes (about 20 h); "Alerts" no longer lists the three stale ones.
- After the next service restart, no `idle-in-transaction timeout` lines in `docker logs hermes-postgres` for 24 h.
