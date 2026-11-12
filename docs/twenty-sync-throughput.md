# Twenty sync throughput: why the queue does not drain, and the permanent fix (2026-11-12)

Measured read-only on the production sync (no changes made). Companion to `twenty-sync-fixes.md`.

## What limits the send rate

| Fact | Measured / read from code |
|---|---|
| One worker, one request at a time | `concurrency: 1` in `automation/config.mjs` |
| Pacing between Twenty calls | `rateIntervalMs: 1100` (one call every 1.1 s), `automation/twenty.mjs` |
| Calls per event | about 3 to 5: read the directory, read the record, **write**, then read back to verify (`find()` before and after `apply()`) |
| Resulting ceiling | about 19 events/minute at best, roughly **600 to 1,100 per hour** (observed 14:29 to 14:48 UTC) |
| Arrivals right now | about 850 events/hour while the source poll catches up after the outage (564 new pending in 40 minutes) |
| Queue order | strict first-in-first-out by `sequence` (verified: sent 233620 to 234039, oldest waiting starts at 234040) |

So the rate is not a fault and nothing is stuck: the sender is working flat out and arrivals are about equal to
its capacity, which is why the backlog (about 880) and the recovery of the 6,150 "processing" items barely move.
(The "122 per hour" figure seen right after the 12 Nov restart was only the first partial hour.)

## Where the capacity goes: duplicate recalculations

About 94% of what is sent is `*_ACTIVITY_RECALCULATE` / `*_SCORE_RECALCULATE`, not real data changes.
Most of it is repeated work for the same entity:

| Waiting now | Events | Distinct entities |
|---|---|---|
| CONTACT activity recalculation | 314 | 64 (about 5 each) |
| CONTACT score recalculation | 314 | 64 |
| COMPANY activity / score | 85 + 85 | 77 |
| Hiring signal / contact upserts | 69 + 2 | 71 |
| **Total** | **869** | **353 (60% repeats)** |

Over the last 24 hours: 1,748 events for about 600 distinct entity+type pairs (two thirds repeats).
A recruiter who sends a burst of emails produces one recalculation per signal, and each carries its own
snapshot (`asOf`, counts). Only the newest snapshot matters; older ones are overwritten by it. The worker
already treats an older `sourceVersion` as `STALE_EVENT` without calling Twenty (`worker.mjs`), but because the
queue is FIFO the old ones are processed (and written to Twenty) first.

## Permanent fix, in order of value

1. **Newest-first per entity (recommended, small).** `company-priority.mjs` already does this for companies
   (`ORDER BY ... l.sequence DESC`, then the worker stales the older events cheaply). Extend the same candidate
   selection to the CONTACT recalculation types, and to HIRING_SIGNAL_UPSERT repeats if any. Expected effect:
   about 60 to 66% fewer Twenty calls, so net drain capacity goes from about 200/hour to about 800/hour during
   catch-up and the 7,000 outstanding events clear in roughly half a day instead of days.
2. **Debounce at the source.** In `activity-clock.mjs` / `projector.mjs`, do not enqueue a second
   recalculation for an entity while one is still PENDING (supersede it instead). Same saving, and the queue
   stops growing with duplicates.
3. **Fewer reads per write.** `find()` runs `refreshDirectory()` and a filtered list twice per event (before
   and after the write). Reuse the first read for the pre-write check, and verify by the mutation's returned
   fields where the contract allows. Saves 1 to 2 calls of about 5.
4. **Raise the pacing only with evidence.** 1.1 s was chosen to stay under Twenty's API limit. Confirm Twenty's
   actual limit and 429 history (`stats.rateLimits`) before lowering `rateIntervalMs` or allowing concurrency 2.

Items 1 and 2 remove the load; 3 and 4 only speed up the same load and should come after.

## Why this was not applied from Hermes

Every file under `automation/` is covered by the signed runtime fingerprint
(`RUNTIME_FINGERPRINT_NOT_APPROVED` if any byte changes) and the sync has no automated tests in the runtime
directory. The change must be made by the sync owner in its source repo, tested there, re-signed and
restarted (same procedure as `twenty-fields-review.md`). Rewriting rows in the live `outbox` to emulate item 1
was deliberately not done: the audit log is hash-chained and the worker's checkpoints assume it wrote those
states itself.

## Interim, without touching the sync

- Avoid bulk re-processing of old emails while the queue drains; I have not measured how much of it reaches
  the sync, so treat it as a precaution.
- Watch Sync status: "Updates sent to Twenty" waiting count should fall once the post-outage catch-up
  burst ends (arrivals drop back to about 70/hour from the 24-hour average).
