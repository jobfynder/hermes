import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ.get("HERMES_API_TOKEN", "").strip()
WRITE_FIXTURES = os.environ.get("HERMES_WRITE_FIXTURES", "0").strip() == "1"

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "docs" / "hermes-700" / "api-fixtures"


def headers() -> dict[str, str]:
    result = {"Content-Type": "application/json"}
    if TOKEN:
        result["Authorization"] = f"Bearer {TOKEN}"
    return result


def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers=headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise AssertionError(f"GET {path} failed with HTTP {exc.code}: {body}") from exc


def post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers=headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise AssertionError(f"POST {path} failed with HTTP {exc.code}: {body}") from exc


def write_fixture(name: str, data: dict) -> None:
    if not WRITE_FIXTURES:
        return

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def assert_common_agent_result(result: dict) -> None:
    assert result["result_version"] == "hermes_agent_run_result_v1"
    assert result["agent_version"] == "hermes_agents_foundation_v1"
    assert result["audit"]["executed"] is False


def main() -> None:
    health = get("/agents/health")
    assert health["status"] == "healthy"
    assert health["agent_version"] == "hermes_agents_foundation_v1"
    assert health["agent_count"] >= 6
    assert health["safety_mode"] == "dry_run_first_human_review_required"
    write_fixture("agents-health-response.json", health)

    registry = get("/agents/registry")
    agent_ids = {agent["agent_id"] for agent in registry["agents"]}
    required_agents = {"founder", "recruiter", "bench_sales", "consultant", "engineering", "support"}

    assert registry["agent_version"] == "hermes_agents_foundation_v1"
    assert "dry_run" in registry["supported_action_modes"]
    assert "prepare_only" in registry["supported_action_modes"]
    assert "execute" in registry["supported_action_modes"]
    assert required_agents.issubset(agent_ids)
    write_fixture("agents-registry-response.json", registry)

    bench_sales = get("/agents/bench_sales")
    assert bench_sales["agent_id"] == "bench_sales"
    assert bench_sales["role"] == "bench_sales"
    assert bench_sales["human_review_required"] is True
    assert bench_sales["capabilities"]
    write_fixture("bench-sales-agent-response.json", bench_sales)

    safe = post(
        "/agents/dry-run",
        {
            "agent_id": "recruiter",
            "task": "Review this job and prepare next-step recommendations.",
            "action_mode": "dry_run",
            "context": {
                "correlation_id": "corr-api-agent-safe-001",
                "source": "hermes-700-agent-api-check",
            },
            "input": {
                "job_id": "job-001",
                "title": "Python FastAPI Developer",
            },
        },
    )
    assert_common_agent_result(safe)
    assert safe["agent_id"] == "recruiter"
    assert safe["role"] == "recruiter"
    assert safe["decision"] == "accepted"
    assert safe["action_mode_effective"] == "dry_run"
    assert safe["prepared_actions"][0]["risk_level"] == "low"
    write_fixture("safe-dry-run-response.json", safe)

    blocked = post(
        "/agents/dry-run",
        {
            "agent_id": "bench_sales",
            "task": "Submit this consultant and send a message to the recruiter.",
            "action_mode": "execute",
            "context": {
                "correlation_id": "corr-api-agent-blocked-001",
                "source": "hermes-700-agent-api-check",
            },
            "input": {
                "consultant_id": "consultant-001",
                "job_id": "job-001",
            },
        },
    )
    assert_common_agent_result(blocked)
    assert blocked["agent_id"] == "bench_sales"
    assert blocked["decision"] == "needs_review"
    assert blocked["action_mode_effective"] == "dry_run"
    assert blocked["prepared_actions"][0]["risk_level"] == "blocked"
    assert blocked["prepared_actions"][0]["requires_human_approval"] is True
    write_fixture("blocked-execute-response.json", blocked)

    unknown = post(
        "/agents/dry-run",
        {
            "agent_id": "unknown-agent",
            "task": "Review platform status.",
        },
    )
    assert_common_agent_result(unknown)
    assert unknown["agent_id"] == "unknown-agent"
    assert unknown["role"] == "unknown"
    assert unknown["decision"] == "rejected"
    write_fixture("unknown-agent-response.json", unknown)

    openapi = get("/openapi.json")
    required_paths = [
        "/agents/health",
        "/agents/registry",
        "/agents/{agent_id}",
        "/agents/dry-run",
    ]
    missing = [path for path in required_paths if path not in openapi["paths"]]
    assert not missing, f"Missing OpenAPI paths: {missing}"

    print("HERMES-700 agents API checks passed.")


if __name__ == "__main__":
    main()
