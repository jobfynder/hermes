#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${HERMES_BASE_URL:-http://127.0.0.1:8000}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "=== HERMES-200 SMOKE TEST ==="
echo "BASE_URL=$BASE_URL"

echo ""
echo "=== health ==="
curl -sS "$BASE_URL/health" -o "$TMP_DIR/health.json"
python3 - "$TMP_DIR/health.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
assert data["status"] == "healthy", data
print({"health": "ok", "version": data.get("version")})
PY

echo ""
echo "=== parse-text good resume ==="
curl -sS -X POST "$BASE_URL/understanding/parse-text" \
  -H "Content-Type: application/json" \
  -d '{"content":"Senior Python Developer with FastAPI, PostgreSQL, Docker, AWS, Kafka and 8 years experience.","document_kind":"resume"}' \
  -o "$TMP_DIR/good.json"

python3 - "$TMP_DIR/good.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
skills = {item["name"] for item in data["structured_data"]["skills"]}

assert data["result_version"] == "hermes_understanding_result_v1", data
assert data["parser_version"] == "basic_local_parser_v1", data
assert data["schema_version"] == "hermes_understanding_v1", data
assert data["quality"]["confidence"] >= 0.7, data["quality"]
assert data["quality"]["needs_fallback"] is False, data["quality"]
assert data["structured_data"]["years_experience"] == 8, data["structured_data"]
assert {"Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Kafka"}.issubset(skills), skills
assert data["llm_context"]["original_token_count"] > 0, data["llm_context"]

print({
    "parse_text_good": "ok",
    "result_version": data["result_version"],
    "parser_version": data["parser_version"],
    "schema_version": data["schema_version"],
    "skills": sorted(skills),
    "years_experience": data["structured_data"]["years_experience"],
})
PY

echo ""
echo "=== parse-text weak fallback ==="
curl -sS -X POST "$BASE_URL/understanding/parse-text" \
  -H "Content-Type: application/json" \
  -d '{"content":"12345","document_kind":"unknown"}' \
  -o "$TMP_DIR/weak.json"

python3 - "$TMP_DIR/weak.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))

assert data["quality"]["needs_fallback"] is True, data["quality"]
assert "no_alpha_text" in data["quality"]["reasons"], data["quality"]
assert "extraction_quality_requires_fallback" in data["validation"]["warnings"], data["validation"]

print({
    "parse_text_weak": "ok",
    "confidence": data["quality"]["confidence"],
    "reasons": data["quality"]["reasons"],
    "validation_warnings": data["validation"]["warnings"],
})
PY

echo ""
echo "=== parse-file txt upload ==="
echo "Java developer with Spring Boot, AWS, PostgreSQL, Kafka, Docker and 10 years experience." > "$TMP_DIR/sample.txt"

curl -sS -X POST "$BASE_URL/understanding/parse-file" \
  -F "document_kind=job_description" \
  -F "file=@$TMP_DIR/sample.txt;type=text/plain" \
  -o "$TMP_DIR/file.json"

python3 - "$TMP_DIR/file.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
skills = {item["name"] for item in data["structured_data"]["skills"]}

assert data["extracted_text"]["source"] == "plain_text", data["extracted_text"]
assert data["structured_data"]["years_experience"] == 10, data["structured_data"]
assert {"Java", "Spring Boot", "AWS", "PostgreSQL", "Kafka", "Docker"}.issubset(skills), skills

print({
    "parse_file_txt": "ok",
    "source": data["extracted_text"]["source"],
    "skills": sorted(skills),
})
PY

echo ""
echo "=== job description field extraction ==="
curl -sS -X POST "$BASE_URL/understanding/parse-text" \
  -H "Content-Type: application/json" \
  -d '{"content":"Need Java backend developer with Spring Boot, AWS, PostgreSQL, Kafka, Docker and 10 years experience.\nLocation: Dallas, TX\nEmployment Type: Contract\nWork Authorization: H1B\nRate: $65-75/hr","document_kind":"job_description"}' \
  -o "$TMP_DIR/jd_fields.json"

python3 - "$TMP_DIR/jd_fields.json" <<'PYJDFIELDS'
import json
import sys

data = json.load(open(sys.argv[1]))
structured = data["structured_data"]

assert structured["job_title"] == "Java backend developer", structured
assert structured["location"] == "Dallas, TX", structured
assert structured["employment_type"] == "Contract", structured
assert structured["work_authorization"] == "H1B", structured
assert structured["rate_or_salary"] == "$65-75/hr", structured
assert structured["years_experience"] == 10, structured

print({
    "jd_field_extraction": "ok",
    "job_title": structured["job_title"],
    "location": structured["location"],
    "employment_type": structured["employment_type"],
    "work_authorization": structured["work_authorization"],
    "rate_or_salary": structured["rate_or_salary"],
})
PYJDFIELDS

echo ""
echo "=== job description required/preferred skills ==="
curl -sS -X POST "$BASE_URL/understanding/parse-text" \
  -H "Content-Type: application/json" \
  -d '{"content":"Need Java backend developer with 10 years experience.\nRequired Skills: Java, Spring Boot, PostgreSQL, Kafka\nPreferred Skills: AWS, Docker\nLocation: Dallas, TX\nEmployment Type: Contract\nWork Authorization: H1B\nRate: $65-75/hr","document_kind":"job_description"}' \
  -o "$TMP_DIR/jd_required_preferred.json"

python3 - "$TMP_DIR/jd_required_preferred.json" <<'PYJDREQPREF'
import json
import sys

data = json.load(open(sys.argv[1]))
structured = data["structured_data"]

required = {item["name"] for item in structured["required_skills"]}
preferred = {item["name"] for item in structured["preferred_skills"]}

assert {"Java", "Spring Boot", "PostgreSQL", "Kafka"}.issubset(required), structured
assert {"AWS", "Docker"}.issubset(preferred), structured

print({
    "jd_required_preferred_skills": "ok",
    "required_skills": sorted(required),
    "preferred_skills": sorted(preferred),
})
PYJDREQPREF

echo ""
echo "=== resume contact extraction ==="
curl -sS -X POST "$BASE_URL/understanding/parse-text" \
  -H "Content-Type: application/json" \
  -d '{"content":"Senior Python Developer\nEmail: alex.kumar@example.com\nPhone: 214-555-7890\nLinkedIn: linkedin.com/in/alex-kumar\nWork Authorization: H1B\nSkills: Python, FastAPI, PostgreSQL, Docker, AWS, Kafka\n8 years experience.","document_kind":"resume"}' \
  -o "$TMP_DIR/contact.json"

python3 - "$TMP_DIR/contact.json" <<'PYCONTACT'
import json
import sys

data = json.load(open(sys.argv[1]))
structured = data["structured_data"]

assert structured["email"] == "alex.kumar@example.com", structured
assert structured["phone"] == "214-555-7890", structured
assert structured["linkedin_url"] == "https://linkedin.com/in/alex-kumar", structured
assert structured["work_authorization"] == "H1B", structured
assert structured["years_experience"] == 8, structured

print({
    "contact_extraction": "ok",
    "email": structured["email"],
    "phone": structured["phone"],
    "linkedin_url": structured["linkedin_url"],
    "work_authorization": structured["work_authorization"],
})
PYCONTACT

echo ""
echo "=== skills taxonomy endpoint ==="
curl -sS "$BASE_URL/understanding/taxonomy/skills" -o "$TMP_DIR/taxonomy.json"

python3 - "$TMP_DIR/taxonomy.json" <<'PYTAXONOMY'
import json
import sys

data = json.load(open(sys.argv[1]))

assert data["version"] == "jobfynder_skills_v1", data
assert len(data["skills"]) >= 30, data
assert any(skill["name"] == "Python" for skill in data["skills"]), data["skills"]

print({
    "taxonomy_endpoint": "ok",
    "version": data["version"],
    "skill_count": len(data["skills"]),
})
PYTAXONOMY

echo ""
echo "HERMES-200 smoke test passed"
