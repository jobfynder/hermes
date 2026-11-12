# jfcrm-sync: skip superseded recalculations (fix #1 in docs/twenty-sync-throughput.md)

**Status: built and tested, NOT deployed.** The runtime refuses to start if any file differs from the signed
activation approval (`RUNTIME_FINGERPRINT_NOT_APPROVED`), and the approval is signed with the founder's key,
which Hermes does not have. Deploying needs the founder's signature (step 2).

## What it changes

`automation/worker.mjs`: one added check, placed next to the existing `STALE_EVENT` / `STALE_CALCULATION`
checks, before any Twenty call. For a `*_RECALCULATE` event, if a **newer** event (higher `sourceVersion`) for the
same entity and the same event type is already in the outbox and is not itself `STALE` or `QUARANTINED`, the
older one is marked `STALE` (new audit action `STALE_SUPERSEDED`) and no Twenty call is made. The newest snapshot
is always processed. `automation/schema.sql` gains one index, `outbox_supersede_lookup`, so the check is an index
lookup and not a scan of the 234k-row outbox. Upserts (`*_UPSERT`) are not touched.

Why this is safe: a recalculation event carries the whole snapshot (`asOf`, counts, lists). The newer snapshot
overwrites everything the older one would write, and the existing worker already treats older snapshots as STALE
once a newer one has been processed; this only does it earlier and without the Twenty calls. STALE rows are
already ignored by dependency checks and by `company-priority`.

Expected effect (measured on 12 Nov): 60% of waiting events and about two thirds of the last 24 hours' events are
repeats, so about 60 to 66% fewer Twenty calls.

## Tested

`./run-test.sh` (on the droplet; throwaway Postgres, real events of one contact, a fake Twenty gateway):

| Case | Unpatched | Patched |
|---|---|---|
| Oldest of 5 queued snapshots | processed (RETRY, would call Twenty) | `STALE`, 0 Twenty calls, audit row, inbox row STALE |
| Newest snapshot | processed | processed |
| Older snapshot whose newer ones are all quarantined | processed | processed |

**End to end** (`./run-e2e.sh`, 12 Nov 2026): throwaway Postgres 16 + RabbitMQ 3, the real `OutboxPublisher`,
`RabbitBroker` (provisioned topology, confirm channel, prefetch 1), `SyncWorker` (outbox proof on) and `PgStore`,
with 9 real queued recalculation events of one contact and an in-memory Twenty:

| | Current code | Patched |
|---|---|---|
| Inbox result | 9 VERIFIED | 8 STALE, 1 VERIFIED |
| Twenty reads | 26 | 2 |
| Twenty writes | 1 | 1 |
| Checkpoint after the run | newest version (60) | newest version (60) |
| Final Twenty record equals newest snapshot | yes | yes (identical) |
| Outbox | 9 PUBLISHED | 9 PUBLISHED |

Real production Twenty was never contacted (writing test data into the live CRM was out of scope), and the
production service, activation gates and scheduler were not run. Roll out and watch (step 4).

## Deploy (owner), in this order

New runtime fingerprint of the patched code: `361d249c37ebd945927163a790539edb0d0a8c90278e6448d35107ad0645efc9`
(current: `737c526e...9adf`). Recompute after applying if anything else changed: `runtimeFingerprint()` in
`automation/fingerprint.mjs`.

1. **Index first** (additive, no lock on writes):
   `docker exec -i hermes-postgres psql -U hermes -d hermes < 001-outbox-supersede-index.sql`
2. **Sign.** Create the next activation manifest (copy of `activation-key-renewal-20261110.json` with
   `runtimeFingerprint` set to the value above, new `approvedAt`/`approvedBy`) and sign it with the activation
   key as for the earlier `activation-*.json` files. Point `SYNC_ACTIVATION_MANIFEST` at it.
3. **Apply and restart together** (the fingerprint is checked at each session start, so do not patch without the
   signed file in place):
   ```
   cd /opt/jfcrm/runtime-20261104/automation && cp worker.mjs worker.mjs.pre-supersede && cp schema.sql schema.sql.pre-supersede
   node /path/to/apply-patch.mjs /opt/jfcrm/runtime-20261104
   systemctl restart jfcrm-sync
   ```
4. **Verify** on the Sync status page for 30 to 60 minutes: service `active` with 0 new restarts; "waiting to
   send" falls faster than before; `audit` shows `STALE_SUPERSEDED` rows; no new `UNSUPPORTED_DESTINATION_DRIFT`
   or quarantine entries; sample a few contacts in Twenty and confirm the newest values.

## Rollback

Restore `worker.mjs.pre-supersede` and `schema.sql.pre-supersede`, point `SYNC_ACTIVATION_MANIFEST` back at the
previous activation file, `systemctl restart jfcrm-sync`. Optionally `DROP INDEX CONCURRENTLY IF EXISTS
jfcrm_sync.outbox_supersede_lookup;`. Events already marked STALE stay STALE (they were overwritten by newer
snapshots, so nothing is lost).

## Not included (later, lower value)

Source-side debounce (`activity-clock.mjs` / `projector.mjs`), fewer reads per write, and a lower
`rateIntervalMs` are described in `docs/twenty-sync-throughput.md`.
