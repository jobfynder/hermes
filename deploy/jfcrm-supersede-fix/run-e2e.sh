#!/usr/bin/env bash
# Run ON the droplet. Throwaway Postgres + RabbitMQ containers; the production runtime code is copied, never modified.
# Usage: run-e2e.sh <runtime-dir> <events.jsonl>   (events.jsonl: >=3 queued recalculation events of ONE entity)
set -euo pipefail
RUNTIME="${1:-/opt/jfcrm/runtime-20261104}"
EVENTS="${2:-/tmp/sample_events.jsonl}"
HERE="$(cd "$(dirname "$0")" && pwd)"
W="$(mktemp -d)"
cleanup() { docker rm -f jfcrm-e2e-pg jfcrm-e2e-mq >/dev/null 2>&1 || true; rm -rf "$W"; }
trap cleanup EXIT
cp -a "$RUNTIME" "$W/base"
cp -a "$RUNTIME" "$W/patched"
node "$HERE/apply-patch.mjs" "$W/patched" >/dev/null
docker run -d --rm --name jfcrm-e2e-pg -e POSTGRES_PASSWORD=t -p 127.0.0.1:55439:5432 postgres:16 >/dev/null
docker run -d --rm --name jfcrm-e2e-mq -p 127.0.0.1:55672:5672 rabbitmq:3-management >/dev/null
for _ in $(seq 60); do docker exec jfcrm-e2e-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 90); do docker logs jfcrm-e2e-mq 2>&1 | grep -q "Time to start RabbitMQ" && break; sleep 2; done
sleep 3
PG=postgres://postgres:t@127.0.0.1:55439/postgres
MQ=amqp://guest:guest@127.0.0.1:55672/
for v in base patched; do
  docker exec jfcrm-e2e-mq rabbitmqctl -q delete_queue jfcrm.sync.v1 >/dev/null 2>&1 || true
  echo "== $v"
  node "$HERE/test-e2e-broker.mjs" "$W/$v" "$EVENTS" "$PG" "$MQ" "$v" | tail -1
done
