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
