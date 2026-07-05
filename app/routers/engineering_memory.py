from fastapi import APIRouter, Body, Depends

from app.engineering_memory.memory_service import generate_memory_from_current_repo
from app.engineering_memory.schemas import GitHubEngineeringMemoryInput
from app.security.rbac import require_permission

router = APIRouter()


@router.post("/v1/engineering-memory/generate")
def generate_engineering_memory(
    event: GitHubEngineeringMemoryInput | None = Body(default=None),
    user: dict = Depends(require_permission("engineering_memory:write")),
):
    return generate_memory_from_current_repo(event)
