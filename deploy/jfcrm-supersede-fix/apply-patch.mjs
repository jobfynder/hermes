// Usage: node apply-patch.mjs <runtime-dir>
// Adds "superseded recalculation" detection to automation/worker.mjs and the supporting index to schema.sql.
// Exits non-zero (and changes nothing) if the anchor text is not found exactly once.
import { readFile, writeFile } from 'node:fs/promises';

const dir = process.argv[2];
if (!dir) {
  console.error('usage: node apply-patch.mjs <runtime-dir>');
  process.exit(2);
}
const file = `${dir}/automation/worker.mjs`;
const src = await readFile(file, 'utf8');
if (src.includes('STALE_SUPERSEDED')) {
  console.log('already patched');
  process.exit(0);
}

const anchor =
  "if(old&&BigInt(old.source_version)===BigInt(e.sourceVersion))assert(old.payload_checksum===eventDigest(e),'SOURCE_VERSION_COLLISION');";
if (src.split(anchor).length !== 2) {
  console.error('anchor not found exactly once');
  process.exit(1);
}

// If a NEWER event for the same entity and recalculation type is already queued (and is not itself
// stale or quarantined), this older snapshot is fully overwritten by it: mark it STALE without calling Twenty.
const insert =
  "if(e.eventType.endsWith('_RECALCULATE')){" +
  "const newer=(await db.query(`SELECT 1 FROM jfcrm_sync.outbox o LEFT JOIN jfcrm_sync.inbox i ON i.idempotency_key=o.idempotency_key " +
  "WHERE o.event->>'canonicalEntityId'=$1 AND o.event->>'eventType'=$2 AND (o.event->>'sourceVersion')::bigint>$3::bigint " +
  "AND (i.event_id IS NULL OR i.status NOT IN ('STALE','QUARANTINED')) LIMIT 1`," +
  '[e.canonicalEntityId,e.eventType,String(e.sourceVersion)])).rows[0];' +
  'if(newer){await db.query("UPDATE jfcrm_sync.inbox SET status=\'STALE\',last_error=NULL,updated_at=now() WHERE idempotency_key=$1",[e.idempotencyKey]);' +
  "await this.store.audit('STALE_SUPERSEDED',{eventType:e.eventType,sourceVersion:e.sourceVersion},e);return{status:'STALE'};}}";
await writeFile(file, src.replace(anchor, () => insert + anchor));

const schema = `${dir}/automation/schema.sql`;
const sql = await readFile(schema, 'utf8');
if (!sql.includes('outbox_supersede_lookup')) {
  await writeFile(
    schema,
    sql.replace(/\s*$/, '\n') +
      "CREATE INDEX IF NOT EXISTS outbox_supersede_lookup ON jfcrm_sync.outbox ((event->>'canonicalEntityId'),(event->>'eventType'),((event->>'sourceVersion')::bigint) DESC);\n",
  );
}
console.log('patched', file);
