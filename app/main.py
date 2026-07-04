from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.messages import router as messages_router
from app.routers.consultants import router as consultants_router
from app.routers.engineering_memory import router as engineering_memory_router

app = FastAPI(
    title="Hermes",
    version="0.2.0",
)

app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(messages_router)
app.include_router(consultants_router)
app.include_router(engineering_memory_router)
