import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.models import AgentContext, AgentRunRequest
from app.agents.service import get_agent_health, get_agent, list_agents, run_agent


def test_health():
    health = get_agent_health()
    assert health.status == "healthy"
    assert health.agent_version == "hermes_agents_foundation_v1"
    assert health.agent_count >= 6
    assert health.safety_mode == "dry_run_first_human_review_required"


def test_registry():
    registry = list_agents()
    ids = {agent.agent_id for agent in registry.agents}

    assert "founder" in ids
    assert "recruiter" in ids
    assert "bench_sales" in ids
    assert "consultant" in ids
    assert "engineering" in ids
    assert "support" in ids
    assert "dry_run" in registry.supported_action_modes


def test_agent_detail():
    agent = get_agent("bench_sales")
    assert agent is not None
    assert agent.role == "bench_sales"
    assert agent.human_review_required is True
    assert agent.capabilities


def test_safe_dry_run():
    request = AgentRunRequest(
        agent_id="recruiter",
        task="Review this job and prepare next-step recommendations.",
        action_mode="dry_run",
        capability_id="job_review",
        context=AgentContext(
            correlation_id="corr-agent-001",
            source="script-check",
            permissions=["agents:read", "agents:run", "matching:evaluate", "submissions:evaluate"],
        ),
        input={"job_id": "job-001"},
    )

    result = run_agent(request)

    assert result.decision == "accepted"
    assert result.action_mode_effective == "dry_run"
    assert result.audit["executed"] is False
    assert result.prepared_actions
    assert result.handoff is not None
    assert result.handoff.handoff_version == "hermes_agent_handoff_v1"
    assert result.handoff.status == "prepared"
    assert result.handoff.target == "human_review"
    assert result.handoff.requires_human_approval is True


def test_blocked_execute():
    request = AgentRunRequest(
        agent_id="bench_sales",
        task="Submit this consultant and send a message to the recruiter.",
        action_mode="execute",
        capability_id="submission_packet",
        context=AgentContext(
            correlation_id="corr-agent-002",
            source="script-check",
            permissions=["agents:read", "agents:run", "matching:evaluate", "submissions:evaluate"],
        ),
        input={"consultant_id": "consultant-001", "job_id": "job-001"},
    )

    result = run_agent(request)

    assert result.decision == "needs_review"
    assert result.action_mode_effective == "dry_run"
    assert result.audit["executed"] is False
    assert result.prepared_actions[0].risk_level == "blocked"
    assert result.prepared_actions[0].requires_human_approval is True
    assert result.handoff is not None
    assert result.handoff.status == "blocked"
    assert result.handoff.requires_human_approval is True


def test_missing_permission_policy():
    request = AgentRunRequest(
        agent_id="recruiter",
        capability_id="job_review",
        task="Review this job.",
        action_mode="dry_run",
        context=AgentContext(
            correlation_id="corr-agent-003",
            source="script-check",
            permissions=["agents:read"],
        ),
        input={"job_id": "job-001"},
    )

    result = run_agent(request)

    assert result.decision == "needs_review"
    assert result.audit["executed"] is False
    assert result.audit["policy"]["allowed"] is False
    assert "agents:run" in result.audit["policy"]["missing_permissions"]


def test_unknown_capability_policy():
    request = AgentRunRequest(
        agent_id="recruiter",
        capability_id="not_real",
        task="Review this job.",
        action_mode="dry_run",
        context=AgentContext(
            correlation_id="corr-agent-004",
            source="script-check",
            permissions=["*"],
        ),
        input={"job_id": "job-001"},
    )

    result = run_agent(request)

    assert result.decision == "rejected"
    assert result.audit["executed"] is False
    assert result.audit["policy"]["allowed"] is False


def test_unknown_agent():
    request = AgentRunRequest(
        agent_id="unknown-agent",
        task="Review platform status.",
    )

    result = run_agent(request)

    assert result.decision == "rejected"
    assert result.role == "unknown"
    assert result.audit["executed"] is False


if __name__ == "__main__":
    test_health()
    test_registry()
    test_agent_detail()
    test_safe_dry_run()
    test_blocked_execute()
    test_missing_permission_policy()
    test_unknown_capability_policy()
    test_unknown_agent()
    print("HERMES-700 agent registry checks passed.")
