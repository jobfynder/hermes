from app.agents.models import (
    AgentCapability,
    AgentDefinition,
    AgentHealthResponse,
    AgentPreparedAction,
    AgentRegistryResponse,
    AgentRunRequest,
    AgentRunResult,
)

AGENT_VERSION = "hermes_agents_foundation_v1"

SUPPORTED_ACTION_MODES = ["dry_run", "prepare_only", "execute"]

BLOCKED_ACTION_KEYWORDS = [
    "send",
    "email",
    "message",
    "submit",
    "approve",
    "verify",
    "deploy",
    "delete",
    "charge",
    "billing",
    "payment",
    "whatsapp",
    "linkedin",
]


def _capability(
    capability_id: str,
    name: str,
    description: str,
    permissions_required: list[str] | None = None,
) -> AgentCapability:
    return AgentCapability(
        capability_id=capability_id,
        name=name,
        description=description,
        permissions_required=permissions_required or [],
        allowed_action_modes=["dry_run", "prepare_only"],
    )


AGENT_REGISTRY: dict[str, AgentDefinition] = {
    "founder": AgentDefinition(
        agent_id="founder",
        role="founder",
        name="Founder Agent",
        description="Prepares founder-level summaries, risks, decisions, and strategic next steps.",
        allowed_permissions=["agents:read", "agents:run", "mission_control:read"],
        capabilities=[
            _capability("executive_summary", "Executive Summary", "Summarize platform state and key decisions."),
            _capability("risk_review", "Risk Review", "Identify risks and safe next steps."),
        ],
    ),
    "recruiter": AgentDefinition(
        agent_id="recruiter",
        role="recruiter",
        name="Recruiter Agent",
        description="Supports recruiter-side job, match, submission, and follow-up workflows.",
        allowed_permissions=["agents:read", "agents:run", "matching:evaluate", "submissions:evaluate"],
        capabilities=[
            _capability("job_review", "Job Review", "Review requirements and explain hiring workflow next steps."),
            _capability("candidate_fit", "Candidate Fit", "Prepare candidate fit reasoning for review."),
        ],
    ),
    "bench_sales": AgentDefinition(
        agent_id="bench_sales",
        role="bench_sales",
        name="Bench Sales Agent",
        description="Supports bench sales matching, submission preparation, duplicate-risk review, and follow-up planning.",
        allowed_permissions=["agents:read", "agents:run", "matching:evaluate", "submissions:evaluate"],
        capabilities=[
            _capability("submission_packet", "Submission Packet", "Prepare submission packet guidance without sending."),
            _capability("follow_up_plan", "Follow-Up Plan", "Prepare recruiter follow-up next steps."),
        ],
    ),
    "consultant": AgentDefinition(
        agent_id="consultant",
        role="consultant",
        name="Consultant Agent",
        description="Supports consultant-facing job-fit explanation, profile improvement, and application-status summaries.",
        allowed_permissions=["agents:read", "agents:run", "matching:evaluate"],
        capabilities=[
            _capability("job_fit_explanation", "Job Fit Explanation", "Explain job fit in plain language."),
            _capability("profile_improvement", "Profile Improvement", "Suggest profile and resume improvements."),
        ],
    ),
    "engineering": AgentDefinition(
        agent_id="engineering",
        role="engineering",
        name="Engineering Agent",
        description="Supports safe engineering summaries, module status, implementation planning, and operational checklists.",
        allowed_permissions=["agents:read", "agents:run", "engineering_memory:write"],
        capabilities=[
            _capability("implementation_plan", "Implementation Plan", "Prepare safe implementation steps."),
            _capability("module_status", "Module Status", "Summarize Hermes module state."),
        ],
    ),
    "support": AgentDefinition(
        agent_id="support",
        role="support",
        name="Support Agent",
        description="Supports user issue summaries, support reply drafts, and safe escalation routing.",
        allowed_permissions=["agents:read", "agents:run"],
        capabilities=[
            _capability("support_summary", "Support Summary", "Summarize user issue and likely resolution path."),
            _capability("reply_draft", "Reply Draft", "Prepare support reply drafts for human review."),
        ],
    ),
}


def get_agent_health() -> AgentHealthResponse:
    return AgentHealthResponse(
        status="healthy",
        agent_version=AGENT_VERSION,
        agent_count=len(AGENT_REGISTRY),
        safety_mode="dry_run_first_human_review_required",
    )


def list_agents() -> AgentRegistryResponse:
    return AgentRegistryResponse(
        supported_action_modes=SUPPORTED_ACTION_MODES,
        agents=list(AGENT_REGISTRY.values()),
    )


def get_agent(agent_id: str) -> AgentDefinition | None:
    return AGENT_REGISTRY.get(agent_id)


def _contains_blocked_action(task: str) -> bool:
    normalized = task.lower()
    return any(keyword in normalized for keyword in BLOCKED_ACTION_KEYWORDS)


def _build_prepared_actions(
    request: AgentRunRequest,
    blocked: bool,
) -> list[AgentPreparedAction]:
    if blocked:
        return [
            AgentPreparedAction(
                action_type="review_required",
                title="Human review required before external or high-risk action",
                description="The requested task appears to involve an external, irreversible, or high-risk action. Hermes prepared this as review-only.",
                risk_level="blocked",
                requires_human_approval=True,
                blocked_reason="HERMES-700 foundation does not allow autonomous external actions.",
                payload={
                    "agent_id": request.agent_id,
                    "requested_action_mode": request.action_mode,
                    "task": request.task,
                },
            )
        ]

    return [
        AgentPreparedAction(
            action_type="next_step_recommendation",
            title="Prepare next-step recommendation",
            description="Hermes can prepare a structured recommendation for human review.",
            risk_level="low",
            requires_human_approval=True,
            payload={
                "agent_id": request.agent_id,
                "task": request.task,
                "input_keys": sorted(request.input.keys()),
            },
        )
    ]


def run_agent(request: AgentRunRequest) -> AgentRunResult:
    agent = get_agent(request.agent_id)

    if not agent:
        return AgentRunResult(
            agent_id=request.agent_id,
            role="unknown",
            decision="rejected",
            action_mode_effective="dry_run",
            summary="Agent was not found in the HERMES-700 registry.",
            risks=["Unknown agent id."],
            next_actions=["Use /agents/registry to select a supported agent."],
            audit={
                "agent_version": AGENT_VERSION,
                "requested_action_mode": request.action_mode,
                "executed": False,
            },
        )

    reasons: list[str] = [
        f"Agent {agent.agent_id} is registered.",
        "HERMES-700 runs agents in dry-run or prepare-only mode by default.",
    ]
    risks: list[str] = []
    next_actions: list[str] = []

    requested_execute = request.action_mode == "execute"
    blocked_action = _contains_blocked_action(request.task)

    if requested_execute:
        risks.append("Execute mode is blocked in the HERMES-700 foundation.")
        next_actions.append("Route this task through a human-approved workflow before execution.")

    if blocked_action:
        risks.append("Task appears to include an external or high-risk action.")
        next_actions.append("Review the prepared action manually before any real-world action.")

    if not request.task.strip():
        risks.append("Task is empty.")
        next_actions.append("Provide a clear task for the agent.")
        decision = "needs_review"
    elif requested_execute or blocked_action:
        decision = "needs_review"
    else:
        decision = "accepted"
        next_actions.append("Review the prepared recommendation and decide whether to create a governed workflow.")

    action_mode_effective = "dry_run" if requested_execute else request.action_mode
    prepared_actions = _build_prepared_actions(request=request, blocked=(requested_execute or blocked_action))

    return AgentRunResult(
        agent_id=agent.agent_id,
        role=agent.role,
        decision=decision,
        action_mode_effective=action_mode_effective,
        summary=f"{agent.name} prepared a safe {action_mode_effective} response for human review.",
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        prepared_actions=prepared_actions,
        audit={
            "agent_version": AGENT_VERSION,
            "agent_role": agent.role,
            "requested_action_mode": request.action_mode,
            "effective_action_mode": action_mode_effective,
            "executed": False,
            "human_review_required": True,
            "correlation_id": request.context.correlation_id,
            "source": request.context.source,
        },
    )
