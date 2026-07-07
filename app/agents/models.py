from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRole = Literal[
    "founder",
    "recruiter",
    "bench_sales",
    "consultant",
    "engineering",
    "support",
]

AgentDecision = Literal["accepted", "needs_review", "rejected"]
AgentActionMode = Literal["dry_run", "prepare_only", "execute"]
AgentRiskLevel = Literal["low", "medium", "high", "blocked"]
AgentHandoffTarget = Literal[
    "human_review",
    "n8n",
    "jobfynder_api",
    "engineering_memory",
    "none",
]
AgentHandoffStatus = Literal["prepared", "blocked", "not_required"]


class AgentCapability(BaseModel):
    capability_id: str
    name: str
    description: str
    permissions_required: list[str] = Field(default_factory=list)
    allowed_action_modes: list[AgentActionMode] = Field(default_factory=lambda: ["dry_run"])


class AgentDefinition(BaseModel):
    agent_id: str
    role: AgentRole
    name: str
    description: str
    allowed_permissions: list[str] = Field(default_factory=list)
    capabilities: list[AgentCapability] = Field(default_factory=list)
    default_action_mode: AgentActionMode = "dry_run"
    human_review_required: bool = True


class AgentContext(BaseModel):
    actor_id: str | None = None
    actor_role: str | None = None
    source: str | None = None
    correlation_id: str | None = None
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunRequest(BaseModel):
    agent_id: str
    task: str
    capability_id: str | None = None
    action_mode: AgentActionMode = "dry_run"
    context: AgentContext = Field(default_factory=AgentContext)
    input: dict[str, Any] = Field(default_factory=dict)


class AgentPreparedAction(BaseModel):
    action_type: str
    title: str
    description: str
    risk_level: AgentRiskLevel = "medium"
    requires_human_approval: bool = True
    blocked_reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentPolicyDecision(BaseModel):
    policy_version: str = "hermes_agent_policy_v1"
    allowed: bool
    decision: AgentDecision
    reason: str
    missing_permissions: list[str] = Field(default_factory=list)
    matched_capability_id: str | None = None
    human_review_required: bool = True


class AgentHandoffEnvelope(BaseModel):
    handoff_version: str = "hermes_agent_handoff_v1"
    status: AgentHandoffStatus = "prepared"
    target: AgentHandoffTarget = "human_review"
    correlation_id: str | None = None
    source_agent_id: str
    source_role: AgentRole | str
    action_mode_effective: AgentActionMode = "dry_run"
    requires_human_approval: bool = True
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentAuditEvent(BaseModel):
    audit_version: str = "hermes_agent_audit_event_v1"
    event_type: str = "agent_run_completed"
    event_id: str
    agent_id: str
    role: AgentRole | str
    capability_id: str | None = None
    decision: AgentDecision
    action_mode_requested: AgentActionMode
    action_mode_effective: AgentActionMode
    executed: bool = False
    human_review_required: bool = True
    policy_version: str | None = None
    handoff_version: str | None = None
    correlation_id: str | None = None
    source: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    risk_count: int = 0
    prepared_action_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    result_version: str = "hermes_agent_run_result_v1"
    agent_version: str = "hermes_agents_foundation_v1"
    agent_id: str
    role: AgentRole | str
    decision: AgentDecision
    action_mode_effective: AgentActionMode = "dry_run"
    summary: str
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    prepared_actions: list[AgentPreparedAction] = Field(default_factory=list)
    handoff: AgentHandoffEnvelope | None = None
    audit_event: AgentAuditEvent | None = None
    audit: dict[str, Any] = Field(default_factory=dict)


class AgentRegistryResponse(BaseModel):
    agent_version: str = "hermes_agents_foundation_v1"
    supported_action_modes: list[AgentActionMode]
    agents: list[AgentDefinition]


class AgentHealthResponse(BaseModel):
    status: str
    agent_version: str
    agent_count: int
    safety_mode: str


class AgentSnapshotResponse(BaseModel):
    snapshot_version: str = "hermes_agent_snapshot_v1"
    status: str = "healthy"
    agent_version: str
    policy_version: str
    handoff_version: str
    audit_version: str
    agent_count: int
    supported_agents: list[str]
    supported_action_modes: list[str]
    safety_mode: str
    execution_mode: str
    api_routes: list[str]
    closure_readiness: dict[str, bool]
