from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router

app = FastAPI(
    title="Hermes",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(jobs_router)