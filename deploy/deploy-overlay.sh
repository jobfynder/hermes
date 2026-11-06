#!/usr/bin/env bash
# One-command, reversible Hermes deploy for the Docker host (run ON the host).
#
#   deploy/deploy-overlay.sh <git-ref> [file ...]
#
# Builds a thin overlay image FROM the image the API is running now, copying
# only the named repo files (default: everything changed between the running
# revision label and <git-ref>), so nothing else in the running image -- or
# its pinned dependencies -- changes. Then recreates hermes-api and
# hermes-backfill-worker, waits for /health, and ROLLS BACK automatically
# (previous compose override restored) if the API does not become healthy.
#
# Backups: the compose override is copied to /opt/hermes-release-backups/<tag>/.
# For schema/data changes take a pg_dump first (docker exec hermes-postgres
# pg_dump -U hermes -Fc hermes > .../hermes.dump); this script does not.
set -uo pipefail

REF="${1:?usage: deploy-overlay.sh <git-ref> [file ...]}"; shift || true
REPO="${HERMES_REPO:-/opt/hermes}"
OVERRIDE="$REPO/docker-compose.override.yml"
TAG="overlay-$(git -C "$REPO" rev-parse --short "$REF")-$(date +%Y%m%d%H%M%S)"
BACKUP="/opt/hermes-release-backups/$TAG"
mkdir -p "$BACKUP" && cp "$OVERRIDE" "$BACKUP/override.before"

CURRENT_IMAGE="$(docker inspect hermes-api --format '{{.Config.Image}}')"
echo "running image: $CURRENT_IMAGE  ->  $TAG"

CTX="$(mktemp -d)"; trap 'rm -rf "$CTX"' EXIT
if [ "$#" -gt 0 ]; then FILES=("$@"); else
  BASE="$(git -C "$REPO" rev-parse "${HERMES_BASE_REF:-HEAD}")"
  mapfile -t FILES < <(git -C "$REPO" diff --name-only "$BASE" "$REF" -- app scripts)
fi
[ "${#FILES[@]}" -gt 0 ] || { echo "no files to deploy"; exit 1; }
for f in "${FILES[@]}"; do mkdir -p "$CTX/$(dirname "$f")"; git -C "$REPO" show "$REF:$f" > "$CTX/$f"; done
{ echo "FROM $CURRENT_IMAGE"; for f in "${FILES[@]}"; do echo "COPY $f /app/$f"; done; } > "$CTX/Dockerfile"
docker build -t "hermes-api:$TAG" "$CTX" || exit 1
docker tag "hermes-api:$TAG" "hermes-backfill:$TAG"

# smoke test in a throwaway, network-less container before touching production
docker run --rm --network none -e DATABASE_URL=dummy -e HERMES_TAXONOMY_RUNTIME_DIR=/tmp/t \
  --entrypoint python "hermes-api:$TAG" -c "from app.main import app" || { echo "import smoke test failed"; exit 1; }

sed -i -E "s#(hermes-api:)[^ ]+#\1$TAG#; s#(hermes-backfill:)[^ ]+#\1$TAG#" "$OVERRIDE"
( cd "$REPO" && docker compose up -d --no-deps hermes-api hermes-backfill-worker )

IP="$(docker inspect hermes-api --format '{{(index .NetworkSettings.Networks "hermes_default").IPAddress}}')"
for _ in $(seq 1 24); do
  sleep 5
  curl -fsS -m 5 "http://$IP:8000/health" >/dev/null 2>&1 && { echo "healthy: $TAG"; exit 0; }
  IP="$(docker inspect hermes-api --format '{{(index .NetworkSettings.Networks "hermes_default").IPAddress}}' 2>/dev/null || echo "$IP")"
done
echo "UNHEALTHY -> rolling back"
cp "$BACKUP/override.before" "$OVERRIDE"
( cd "$REPO" && docker compose up -d --no-deps hermes-api hermes-backfill-worker )
exit 1
