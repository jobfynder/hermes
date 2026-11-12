#!/usr/bin/env bash
# Run ON the droplet. Needs: docker, node, the runtime dir, a sample events file. Uses a throwaway Postgres.
set -euo pipefail
RUNTIME="${1:-/opt/jfcrm/runtime-20261104}"
EVENTS="${2:-/tmp/sample_events.jsonl}"
HERE="$(cd "$(dirname "$0")" && pwd)"
W="$(mktemp -d)"
trap 'docker rm -f jfcrm-fix-pg >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
cp -a "$RUNTIME" "$W/base"
cp -a "$RUNTIME" "$W/patched"
node "$HERE/apply-patch.mjs" "$W/patched"
docker run -d --rm --name jfcrm-fix-pg -e POSTGRES_PASSWORD=t -p 127.0.0.1:55439:5432 postgres:16 >/dev/null
for _ in $(seq 30); do docker exec jfcrm-fix-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
sleep 2
URL=postgres://postgres:t@127.0.0.1:55439/postgres
echo "== baseline (current production code)"
node "$HERE/test-superseded.mjs" "$W/base" "$EVENTS" "$URL" baseline || true
echo "== patched"
node "$HERE/test-superseded.mjs" "$W/patched" "$EVENTS" "$URL" patched
