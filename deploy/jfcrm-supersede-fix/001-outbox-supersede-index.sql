-- Run once on the production database BEFORE restarting the patched sync (additive, safe to repeat).
-- CONCURRENTLY cannot run inside a transaction block: run with psql -f, not inside BEGIN.
CREATE INDEX CONCURRENTLY IF NOT EXISTS outbox_supersede_lookup ON jfcrm_sync.outbox
  ((event->>'canonicalEntityId'),(event->>'eventType'),((event->>'sourceVersion')::bigint) DESC);
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS jfcrm_sync.outbox_supersede_lookup;
