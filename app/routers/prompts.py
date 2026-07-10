from fastapi import APIRouter, Depends, HTTPException

from app.prompt_runtime.models import (
    PromptDefinition,
    PromptHealthResponse,
    PromptRegistryResponse,
    PromptRunRequest,
    PromptRunResult,
)
from app.prompt_runtime.registry import get_prompt, list_prompts
from app.prompt_runtime.service import get_prompt_health, run_prompt
from app.security.rbac import require_permission

router = APIRouter(prefix="/prompts", tags=["Prompt Runtime"])


@router.get("/health", response_model=PromptHealthResponse)
def prompt_runtime_health(
    _user: dict = Depends(require_permission("agents:read")),
) -> PromptHealthResponse:
    return get_prompt_health()


@router.get("/registry", response_model=PromptRegistryResponse)
def prompt_registry(
    _user: dict = Depends(require_permission("agents:read")),
) -> PromptRegistryResponse:
    return list_prompts()


@router.get("/{prompt_id}", response_model=PromptDefinition)
def prompt_detail(
    prompt_id: str,
    _user: dict = Depends(require_permission("agents:read")),
) -> PromptDefinition:
    prompt = get_prompt(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail="prompt_not_found")

    return prompt


@router.post("/run", response_model=PromptRunResult)
def prompt_run(
    request: PromptRunRequest,
    _user: dict = Depends(require_permission("agents:run")),
) -> PromptRunResult:
    return run_prompt(request)
