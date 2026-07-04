from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.messages import router as messages_router
from app.routers.consultants import router as consultants_router
from app.routers.engineering_memory import router as engineering_memory_router
from app.routers.mission_control import router as mission_control_router
from app.routers.session_brief import router as session_brief_router
from app.routers.actions import router as actions_router

app = FastAPI(
    title="Hermes",
    version="0.2.3",
)

app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(messages_router)
app.include_router(consultants_router)
app.include_router(engineering_memory_router)
app.include_router(mission_control_router)
app.include_router(session_brief_router)
app.include_router(actions_router)
