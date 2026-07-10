import json
from pathlib import Path

d = Path("docs/hermes-500/api-fixtures")

required = [
  "README.md",
  "workflow-policy-response.json",
  "evaluate-intro-request.json",
  "evaluate-intro-response.json",
  "evaluate-invalid-transition-request.json",
  "evaluate-invalid-transition-response.json",
  "evaluate-from-handoff-request.json",
  "evaluate-from-handoff-response.json",
  "evaluate-from-handoff-duplicate-request.json",
  "evaluate-from-handoff-duplicate-response.json",
]

missing = [x for x in required if not (d / x).exists()]
if missing:
    raise SystemExit(f"missing fixtures: {missing}")

for p in sorted(d.glob("*.json")):
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"not object: {p}")
    print("valid:", p.name)

print("HERMES-500 API fixture validation passed.")
