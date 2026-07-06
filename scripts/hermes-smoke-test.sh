#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${HERMES_BASE_URL:-http://localhost:8000}"
ADMIN_TOKEN_FILE="${HERMES_ADMIN_TOKEN_FILE:-/root/hermes-admin-token.txt}"
N8N_TOKEN_FILE="${HERMES_N8N_TOKEN_FILE:-/root/hermes-n8n-token.txt}"

echo "Hermes Smoke Test"
echo "-----------------"
echo "Base URL: $BASE_URL"
echo ""

if [ ! -f "$ADMIN_TOKEN_FILE" ]; then
  echo "FAIL: Admin token file not found: $ADMIN_TOKEN_FILE"
  exit 1
fi

if [ ! -f "$N8N_TOKEN_FILE" ]; then
  echo "FAIL: n8n token file not found: $N8N_TOKEN_FILE"
  exit 1
fi

ADMIN_TOKEN="$(tr -d '\r\n' < "$ADMIN_TOKEN_FILE")"
N8N_TOKEN="$(tr -d '\r\n' < "$N8N_TOKEN_FILE")"

check_code() {
  local name="$1"
  local expected="$2"
  local actual="$3"

  if [ "$actual" != "$expected" ]; then
    echo "FAIL: $name expected HTTP $expected but got HTTP $actual"
    exit 1
  fi

  echo "PASS: $name HTTP $actual"
}

health_code="$(curl -s -o /tmp/hermes-health.out -w "%{http_code}" "$BASE_URL/health")"
check_code "health public" "200" "$health_code"

security_no_token_code="$(curl -s -o /tmp/hermes-security-no-token.out -w "%{http_code}" "$BASE_URL/security/rbac/status")"
check_code "security without token blocked" "401" "$security_no_token_code"

security_admin_code="$(curl -s -o /tmp/hermes-security-admin.out -w "%{http_code}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/security/rbac/status")"
check_code "security with admin token" "200" "$security_admin_code"

security_n8n_code="$(curl -s -o /tmp/hermes-security-n8n.out -w "%{http_code}" \
  -H "Authorization: Bearer $N8N_TOKEN" \
  "$BASE_URL/security/rbac/status")"
check_code "security blocked for n8n token" "403" "$security_n8n_code"

message_no_token_code="$(curl -s -o /tmp/hermes-message-no-token.out -w "%{http_code}" \
  -X POST "$BASE_URL/v1/messages/understand" \
  -H "Content-Type: application/json" \
  -d '{"text":"Senior Java Developer with Spring Boot and AWS"}')"
check_code "message endpoint without token blocked" "401" "$message_no_token_code"

message_admin_code="$(curl -s -o /tmp/hermes-message-admin.out -w "%{http_code}" \
  -X POST "$BASE_URL/v1/messages/understand" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"Senior Java Developer with Spring Boot and AWS"}')"
check_code "message endpoint with admin token" "200" "$message_admin_code"

matching_admin_code="$(curl -s -o /tmp/hermes-matching-admin.out -w "%{http_code}" \
  -X POST "$BASE_URL/matching/resume-to-job" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resume":{"skills":["Python","FastAPI","PostgreSQL","Docker"],"years_experience":6,"work_authorization":"H1B","location":"Remote"},"job":{"required_skills":["Python","FastAPI","PostgreSQL"],"preferred_skills":["Docker","Kubernetes"],"years_experience":5,"work_authorization":"H1B","location":"Remote"}}')"
check_code "matching endpoint with admin token" "200" "$matching_admin_code"

python3 - /tmp/hermes-matching-admin.out <<'PYMATCH'
import json
import sys

data = json.load(open(sys.argv[1]))
assert data["decision"] == "submit", data
assert data["match_score"] >= 90, data
assert data["matcher_version"] == "basic_local_matcher_v1", data
print("PASS: matching endpoint response validated")
PYMATCH

from_understanding_code="$(curl -s -o /tmp/hermes-matching-from-understanding.out -w "%{http_code}" \
  -X POST "$BASE_URL/matching/resume-to-job/from-understanding" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resume_result":{"structured_data":{"skills":[{"name":"Python"},{"name":"FastAPI"},{"name":"PostgreSQL"},{"name":"Docker"}],"years_experience":6,"work_authorization":"H1B","location":"Remote"}},"job_result":{"structured_data":{"required_skills":[{"name":"Python"},{"name":"FastAPI"},{"name":"PostgreSQL"}],"preferred_skills":[{"name":"Docker"},{"name":"Kubernetes"}],"years_experience":5,"work_authorization":"H1B","location":"Remote"}}}')"
check_code "matching from-understanding endpoint with admin token" "200" "$from_understanding_code"

python3 - /tmp/hermes-matching-from-understanding.out <<'PYFROMUNDERSTANDING'
import json
import sys

data = json.load(open(sys.argv[1]))
assert data["decision"] == "submit", data
assert data["match_score"] >= 90, data
assert data["matcher_version"] == "basic_local_matcher_v1", data
print("PASS: matching from-understanding response validated")
PYFROMUNDERSTANDING

if docker ps --format '{{.Names}}' | grep -qx "hermes-api"; then
  docker exec hermes-api sh -c 'test ! -d /app/.git'
  echo "PASS: .git not present inside hermes-api container"
else
  echo "WARN: hermes-api container not found; skipped container .git check"
fi

echo ""
echo "Hermes smoke test passed."
