from fastapi import APIRouter

from app.engineering_memory.memory_service import generate_memory_from_current_repo

router = APIRouter()


@router.post("/v1/engineering-memory/generate")
def generate_engineering_memory():
    return generate_memory_from_current_repo()