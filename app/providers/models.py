from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderStatus = Literal[
    "configured",
    "not_configured",
    "contract",
    "degraded",
    "failed",
]


class ProviderHealth(BaseModel):
    provider: str
    status: ProviderStatus
    configured: bool = False
    supports_webhook: bool = False
    supports_files: bool = False
    supports_outbound: bool = False
    webhook_url: str | None = None
    checks: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
