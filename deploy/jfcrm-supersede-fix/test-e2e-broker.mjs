// End-to-end: outbox -> OutboxPublisher -> RabbitMQ -> RabbitBroker.consume -> SyncWorker -> (fake) Twenty -> inbox/checkpoints.
// Usage: node test-e2e-broker.mjs <runtime-dir> <events.jsonl> <postgres-url> <amqp-url> <label>
// The real production classes are used for everything except the Twenty gateway, which is an in-memory fake that
// records writes (production Twenty is never contacted). Prints a JSON summary on the last line.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';

const [dir, eventsFile, pgUrl, amqpUrl, label] = process.argv.slice(2);
const require = createRequire(`${dir}/automation/`);
const { Pool } = require('pg');
const { SyncWorker } = await import(`${dir}/automation/worker.mjs`);
const { PgStore } = await import(`${dir}/automation/store.mjs`);
const { RabbitBroker, OutboxPublisher } = await import(`${dir}/automation/broker.mjs`);
const { eventDigest } = await import(`${dir}/automation/contracts.mjs`);

const events = readFileSync(eventsFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
events.sort((a, b) => Number(a.sourceVersion) - Number(b.sourceVersion));
const first = events[0];
const newest = events[events.length - 1];

const pool = new Pool({ connectionString: pgUrl });
await pool.query('DROP SCHEMA IF EXISTS jfcrm_sync CASCADE');
await pool.query(readFileSync(`${dir}/automation/schema.sql`, 'utf8'));
const store = new PgStore(pool);

// ---- seed: mappings and satisfied dependencies for the contact and its company
const companyTarget = randomUUID();
const contactTarget = randomUUID();
await pool.query(
  "INSERT INTO jfcrm_sync.entity_map(canonical_id,kind,identity,target_id) VALUES($1,'company',$2,$3),($4,'recruiter',$5,$6)",
  [first.body.companyCanonicalId, 'example-company.test', companyTarget, first.canonicalEntityId, first.body.identity, contactTarget],
);
for (const d of first.dependencies ?? []) {
  await pool.query(
    `INSERT INTO jfcrm_sync.checkpoints(canonical_id,event_type,source_version,event_id,target_id,payload_checksum,expected_fields,last_success_at,verification_status)
     VALUES($1,$2,$3,$4,$5,'x','{}'::jsonb,now(),'VERIFIED') ON CONFLICT DO NOTHING`,
    [d.canonicalEntityId, d.eventType, d.sourceVersion, 'seed-' + d.eventType, companyTarget],
  );
}
for (const e of events) {
  await pool.query(
    'INSERT INTO jfcrm_sync.outbox(event_id,idempotency_key,event,payload_checksum) VALUES($1,$2,$3,$4)',
    [e.eventId, e.idempotencyKey, JSON.stringify(e), eventDigest(e)],
  );
}

// ---- fake Twenty (never the real one): in-memory records, counts every write
const company = { id: companyTarget, updatedAt: '2026-11-01T00:00:00.000Z', deletedAt: null, companyType: 'UNKNOWN', workModel: 'UNKNOWN', name: 'Example Co' };
const contact = { id: contactTarget, updatedAt: '2026-11-01T00:00:00.000Z', deletedAt: null, companyId: companyTarget };
const stats = { find: 0, apply: 0 };
const gateway = {
  async find(kind) { stats.find++; return structuredClone(kind === 'company' ? company : contact); },
  async apply(kind, identity, changes) {
    stats.apply++;
    Object.assign(contact, structuredClone(changes), { updatedAt: new Date(Date.now() + stats.apply * 1000).toISOString() });
    return structuredClone(contact);
  },
};

const config = { amqpUrl, brokerVhost: '/', prefix: 'jfcrm.sync.v1', confirmTimeoutMs: 20000, requireOutboxProof: true, eventAttempts: 5 };
const gate = async () => {};
const broker = new RabbitBroker({ config, gate });
await broker.open();
await broker.provision();
await broker.verifyTopology();
const worker = new SyncWorker({ store, gateway, gate, config });
const publisher = new OutboxPublisher({ store, broker, gate });

let published = 0;
while ((await publisher.once()) > 0) published++;
await broker.consume(worker);

const deadline = Date.now() + 60000;
let rows = [];
while (Date.now() < deadline) {
  rows = (await pool.query('SELECT event_id,status,last_error FROM jfcrm_sync.inbox')).rows;
  if (rows.length === events.length && rows.every((r) => ['VERIFIED', 'STALE'].includes(r.status))) break;
  await new Promise((r) => setTimeout(r, 300));
}
await broker.stop();

const byStatus = {};
for (const r of rows) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;
const cp = (await pool.query("SELECT source_version FROM jfcrm_sync.checkpoints WHERE canonical_id=$1 AND event_type=$2", [first.canonicalEntityId, first.eventType])).rows[0];
const outboxStates = (await pool.query('SELECT status,count(*)::int n FROM jfcrm_sync.outbox GROUP BY 1')).rows;
const wanted = Object.fromEntries(Object.entries(newest.body).filter(([k]) =>
  ['requirements7d', 'requirements30d', 'requirements90d', 'lastObservedAt', 'firstObservedAt', 'primarySkills', 'primaryLocations'].includes(k)));
const finalMatchesNewest = Object.entries(wanted).every(([k, v]) => JSON.stringify(contact[k]) === JSON.stringify(v));

const summary = {
  label, events: events.length, published, inboxByStatus: byStatus, twentyWrites: stats.apply, twentyReads: stats.find,
  checkpointVersion: cp?.source_version ?? null, newestVersion: String(newest.sourceVersion),
  outbox: outboxStates, finalTwentyMatchesNewestSnapshot: finalMatchesNewest,
  allTerminal: rows.length === events.length && rows.every((r) => ['VERIFIED', 'STALE'].includes(r.status)),
  errors: rows.filter((r) => r.last_error).map((r) => r.last_error),
};
console.log(JSON.stringify(summary));
await pool.end();
process.exit(0);
