from app.agents.models import (
    AgentCapability,
    AgentDefinition,
    AgentHandoffEnvelope,
    AgentHealthResponse,
    AgentPolicyDecision,
    AgentPreparedAction,
    AgentRegistryResponse,
    AgentRunRequest,
    AgentRunResult,
)

AGENT_VERSION = "hermes_agents_foundation_v1"
AGENT_POLICY_VERSION = "hermes_agent_policy_v1"

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


def _has_permission(actor_permissions: list[str], required_permission: str) -> bool:
    return "*" in actor_permissions or required_permission in actor_permissions


def evaluate_agent_policy(request: AgentRunRequest) -> AgentPolicyDecision:
    agent = get_agent(request.agent_id)

    if not agent:
        return AgentPolicyDecision(
            allowed=False,
            decision="rejected",
            reason="Agent is not registered.",
        )

    matched_capability_id: str | None = None
    required_permissions = list(agent.allowed_permissions)

    if request.capability_id:
        matched_capability = None
        for capability in agent.capabilities:
            if capability.capability_id == request.capability_id:
                matched_capability = capability
                matched_capability_id = capability.capability_id
                break

        if matched_capability is None:
            return AgentPolicyDecision(
                allowed=False,
                decision="rejected",
                reason="Requested capability is not registered for this agent.",
                matched_capability_id=request.capability_id,
            )

        required_permissions.extend(matched_capability.permissions_required)

        if request.action_mode not in matched_capability.allowed_action_modes:
            return AgentPolicyDecision(
                allowed=False,
                decision="needs_review",
                reason="Requested action mode is not allowed for this capability.",
                matched_capability_id=matched_capability_id,
            )

    actor_permissions = request.context.permissions or []
    missing_permissions = [
        permission
        for permission in sorted(set(required_permissions))
        if not _has_permission(actor_permissions, permission)
    ]

    if missing_permissions:
        return AgentPolicyDecision(
            allowed=False,
            decision="needs_review",
            reason="Actor context is missing one or more agent permissions.",
            missing_permissions=missing_permissions,
            matched_capability_id=matched_capability_id,
        )

    return AgentPolicyDecision(
        allowed=True,
        decision="accepted",
        reason="Agent policy allowed this dry-run or prepare-only request.",
        matched_capability_id=matched_capability_id,
    )


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


def build_agent_handoff(
    request: AgentRunRequest,
    result_agent_id: str,
    result_role: str,
    decision: str,
    action_mode_effective: str,
    prepared_actions: list[AgentPreparedAction],
    blocked: bool,
) -> AgentHandoffEnvelope:
    if not prepared_actions:
        return AgentHandoffEnvelope(
            status="not_required",
            target="none",
            correlation_id=request.context.correlation_id,
            source_agent_id=result_agent_id,
            source_role=result_role,
            action_mode_effective=action_mode_effective,  # type: ignore[arg-type]
            reason="No handoff was required for this agent result.",
            payload={},
        )

    status = "blocked" if blocked else "prepared"
    target = "human_review"

    return AgentHandoffEnvelope(
        status=status,  # type: ignore[arg-type]
        target=target,
        correlation_id=request.context.correlation_id,
        source_agent_id=result_agent_id,
        source_role=result_role,
        action_mode_effective=action_mode_effective,  # type: ignore[arg-type]
        requires_human_approval=True,
        reason="Agent output prepared as a controlled handoff for human review.",
        payload={
            "decision": decision,
            "task": request.task,
            "capability_id": request.capability_id,
            "input": request.input,
            "prepared_actions": [action.model_dump() for action in prepared_actions],
        },
    )


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
                "policy_version": AGENT_POLICY_VERSION,
                "requested_action_mode": request.action_mode,
                "executed": False,
            },
        )

    policy = evaluate_agent_policy(request)

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

    if not policy.allowed:
        risks.append(policy.reason)
        if policy.missing_permissions:
            risks.append("Actor context does not include all permissions expected by this agent.")
        next_actions.append("Review actor permissions, capability, and action mode before proceeding.")
        decision = policy.decision
    elif not request.task.strip():
        risks.append("Task is empty.")
        next_actions.append("Provide a clear task for the agent.")
        decision = "needs_review"
    elif requested_execute or blocked_action:
        decision = "needs_review"
    else:
        decision = "accepted"
        next_actions.append("Review the prepared recommendation and decide whether to create a governed workflow.")

    action_mode_effective = "dry_run" if requested_execute else request.action_mode
    handoff_blocked = requested_execute or blocked_action or decision in {"needs_review", "rejected"}
    prepared_actions = _build_prepared_actions(request=request, blocked=(requested_execute or blocked_action))
    handoff = build_agent_handoff(
        request=request,
        result_agent_id=agent.agent_id,
        result_role=agent.role,
        decision=decision,
        action_mode_effective=action_mode_effective,
        prepared_actions=prepared_actions,
        blocked=handoff_blocked,
    )

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
        handoff=handoff,
        audit={
            "agent_version": AGENT_VERSION,
            "agent_role": agent.role,
            "requested_action_mode": request.action_mode,
            "effective_action_mode": action_mode_effective,
            "executed": False,
            "human_review_required": True,
            "policy": policy.model_dump(),
            "correlation_id": request.context.correlation_id,
            "source": request.context.source,
        },
    )
