from fastapi import APIRouter, Body

from app.engineering_memory.memory_service import generate_memory_from_current_repo
from app.engineering_memory.schemas import GitHubEngineeringMemoryInput

router = APIRouter()


@router.post("/v1/engineering-memory/generate")
def generate_engineering_memory(
    event: GitHubEngineeringMemoryInput | None = Body(default=None),
):
    return generate_memory_from_current_repo(event)
