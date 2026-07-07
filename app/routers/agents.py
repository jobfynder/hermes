from fastapi import APIRouter, Depends, HTTPException

from app.agents.models import (
    AgentDefinition,
    AgentHealthResponse,
    AgentRegistryResponse,
    AgentRunRequest,
    AgentRunResult,
)
from app.agents.service import (
    get_agent,
    get_agent_health,
    list_agents,
    run_agent,
)
from app.security.rbac import require_permission

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.get("/health", response_model=AgentHealthResponse)
def agents_health(
    user: dict = Depends(require_permission("agents:read")),
) -> AgentHealthResponse:
    return get_agent_health()


@router.get("/registry", response_model=AgentRegistryResponse)
def agents_registry(
    user: dict = Depends(require_permission("agents:read")),
) -> AgentRegistryResponse:
    return list_agents()


@router.get("/{agent_id}", response_model=AgentDefinition)
def agent_detail(
    agent_id: str,
    user: dict = Depends(require_permission("agents:read")),
) -> AgentDefinition:
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/dry-run", response_model=AgentRunResult)
def agents_dry_run(
    request: AgentRunRequest,
    user: dict = Depends(require_permission("agents:run")),
) -> AgentRunResult:
    return run_agent(request)
