from typing import Any, Literal

from pydantic import BaseModel, Field


PromptRuntimeMode = Literal["dry_run", "live"]
PromptRuntimeDecision = Literal["completed", "blocked", "failed", "needs_review"]


class PromptDefinition(BaseModel):
    prompt_id: str
    name: str
    domain: str = "general"
    version: str
    description: str
    required_variables: list[str] = Field(default_factory=list)
    optional_variables: list[str] = Field(default_factory=list)
    system_template: str
    user_template: str
    safety_policy: str = "hermes_prompt_safety_v1"
    default_model: str = "anthropic/claude-haiku-4-5"
    status: Literal["active", "draft", "deprecated"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptRenderedMessage(BaseModel):
    role: Literal["system", "user"]
    content: str


class PromptHealthResponse(BaseModel):
    status: str = "healthy"
    runtime_version: str
    registry_version: str
    registry_source: str = "langfuse"
    prompt_count: int
    dry_run_default: bool
    litellm_configured: bool
    langfuse_configured: bool
    provider: str
    run_log_enabled: bool
    run_log_dir: str
    safety_policy: str


class PromptRegistryResponse(BaseModel):
    registry_version: str
    prompt_count: int
    prompts: list[PromptDefinition]


class PromptRunRequest(BaseModel):
    prompt_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    mode: PromptRuntimeMode = "dry_run"
    correlation_id: str | None = None
    actor_id: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptSafetyResult(BaseModel):
    policy_version: str = "hermes_prompt_safety_v1"
    allowed: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    human_review_required: bool = True


class PromptRunResult(BaseModel):
    result_version: str = "hermes_prompt_run_result_v1"
    runtime_version: str
    run_id: str
    prompt_id: str
    prompt_version: str
    mode_requested: PromptRuntimeMode
    mode_effective: PromptRuntimeMode
    provider: str
    decision: PromptRuntimeDecision
    rendered_messages: list[PromptRenderedMessage] = Field(default_factory=list)
    output_text: str | None = None
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    safety: PromptSafetyResult = Field(default_factory=PromptSafetyResult)
    usage: dict[str, Any] = Field(default_factory=dict)
    log_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
