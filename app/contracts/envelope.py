from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ExecutionMode = Literal["hermes_only", "hermes_plus_llm", "hermes_plus_cloud"]


class HermesCapabilityEnvelope(BaseModel):
    """Canonical response envelope for every Hermes capability, per the
    Jobfynder Hermes Integration Blueprint v1 section 7.
    """

    request_id: str = Field(default_factory=lambda: f"req_{uuid4()}")
    capability: str
    execution_mode: ExecutionMode
    confidence: float | None = None
    llm_required: bool = False
    llm_prompt_name: str | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)
    unresolved_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    proposed_actions: list[str] = Field(default_factory=list)
    trace_metadata: dict[str, Any] = Field(default_factory=dict)


def build_envelope(
    *,
    capability: str,
    structured_data: dict[str, Any],
    confidence: float | None = None,
    llm_required: bool = False,
    llm_prompt_name: str | None = None,
    unresolved_fields: list[str] | None = None,
    warnings: list[str] | None = None,
    proposed_actions: list[str] | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> HermesCapabilityEnvelope:
    return HermesCapabilityEnvelope(
        capability=capability,
        execution_mode="hermes_plus_llm" if llm_required else "hermes_only",
        confidence=confidence,
        llm_required=llm_required,
        llm_prompt_name=llm_prompt_name,
        structured_data=structured_data,
        unresolved_fields=unresolved_fields or [],
        warnings=warnings or [],
        proposed_actions=proposed_actions or [],
        trace_metadata=trace_metadata or {},
    )
