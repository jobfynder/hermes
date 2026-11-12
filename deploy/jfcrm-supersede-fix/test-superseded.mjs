// Usage: node test-superseded.mjs <runtime-dir> <events.jsonl> <postgres-url> patched|baseline
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const [dir, eventsFile, url, expect] = process.argv.slice(2);
const require = createRequire(`${dir}/automation/`);
const { Pool } = require('pg');
const { SyncWorker } = await import(`${dir}/automation/worker.mjs`);
const { PgStore } = await import(`${dir}/automation/store.mjs`);
const { eventDigest } = await import(`${dir}/automation/contracts.mjs`);

const events = readFileSync(eventsFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
events.sort((a, b) => Number(a.sourceVersion) - Number(b.sourceVersion));
const pool = new Pool({ connectionString: url });
await pool.query('DROP SCHEMA IF EXISTS jfcrm_sync CASCADE');
await pool.query(readFileSync(`${dir}/automation/schema.sql`, 'utf8'));
for (const e of events) {
  await pool.query(
    'INSERT INTO jfcrm_sync.outbox(event_id,idempotency_key,event,payload_checksum) VALUES($1,$2,$3,$4)',
    [e.eventId, e.idempotencyKey, JSON.stringify(e), eventDigest(e)],
  );
}
const calls = { find: 0, apply: 0 };
const gateway = {
  async find() { calls.find++; return null; },
  async apply() { calls.apply++; throw new Error('apply must not run'); },
};
const worker = new SyncWorker({
  store: new PgStore(pool),
  gateway,
  gate: async () => {},
  config: { requireOutboxProof: false, eventAttempts: 5 },
});

let failures = 0;
const check = (name, ok, detail) => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -> ' + detail : ''}`);
  if (!ok) failures++;
};
const oldest = events[0];
const newest = events[events.length - 1];

// 1. an old snapshot with newer ones already queued is skipped without touching Twenty
let r = await worker.process(oldest);
if (expect === 'patched') {
  check('oldest with newer queued -> STALE', r.status === 'STALE', r.status);
  check('no Twenty calls for the superseded event', calls.find === 0 && calls.apply === 0, JSON.stringify(calls));
  const aud = (await pool.query("SELECT count(*)::int n FROM jfcrm_sync.audit WHERE action='STALE_SUPERSEDED'")).rows[0].n;
  check('audit row STALE_SUPERSEDED written', aud === 1, String(aud));
  const st = (await pool.query('SELECT status FROM jfcrm_sync.inbox WHERE event_id=$1', [oldest.eventId])).rows[0]?.status;
  check('inbox row is STALE', st === 'STALE', st);
} else {
  check('baseline: oldest is NOT skipped (proves the test discriminates)', r.status !== 'STALE', r.status);
}

// 2. the newest snapshot is never skipped
r = await worker.process(newest);
check('newest is not STALE', r.status !== 'STALE', r.status);

// 3. when the only newer events are stale/quarantined, they must not supersede an older one
const middle = events[1];
await pool.query(
  "UPDATE jfcrm_sync.inbox SET status='QUARANTINED' WHERE event_id=ANY($1)",
  [events.slice(2).map((e) => e.eventId)],
);
for (const e of events.slice(2)) {
  await pool.query(
    "INSERT INTO jfcrm_sync.inbox(event_id,idempotency_key,payload_checksum,status,attempts) VALUES($1,$2,$3,'QUARANTINED',1) ON CONFLICT DO NOTHING",
    [e.eventId, e.idempotencyKey, eventDigest(e)],
  );
}
r = await worker.process(middle);
check('older event whose newer ones are all quarantined is not skipped', r.status !== 'STALE', r.status);

await pool.end();
console.log(failures ? `\n${failures} FAILED` : '\nALL PASSED');
process.exit(failures ? 1 : 0);
