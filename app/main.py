from fastapi import FastAPI
from app.routers import submissions
from app.routers import integrations
from app.routers import agents

from app.config import HERMES_SERVICE_NAME, HERMES_VERSION

from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.messages import router as messages_router
from app.routers.consultants import router as consultants_router
from app.routers.engineering_memory import router as engineering_memory_router
from app.routers.mission_control import router as mission_control_router
from app.routers.session_brief import router as session_brief_router
from app.routers.actions import router as actions_router
from app.routers.workspace import router as workspace_router
from app.routers.security import router as security_router
from app.routers.understanding import router as understanding_router
from app.routers.matching import router as matching_router
from app.routers.channels import router as channels_router
from app.routers.onboarding import router as onboarding_router
from app.routers.drafts import router as drafts_router
from app.routers.access import router as access_router
from app.routers.telegram_provider import router as telegram_provider_router
from app.routers.providers import router as providers_router
from app.routers.linkedin_provider import router as linkedin_provider_router
from app.routers.brightdata_provider import router as brightdata_provider_router
from app.routers.email_provider import router as email_provider_router
from app.routers.provider_contracts import router as provider_contracts_router
from app.routers.comm_intake import router as comm_intake_router
from app.routers.prompts import router as prompts_router
from app.routers.resume_builder import router as resume_builder_router

app = FastAPI(
    title=HERMES_SERVICE_NAME,
    version=HERMES_VERSION,
)

app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(messages_router)
app.include_router(consultants_router)
app.include_router(engineering_memory_router)
app.include_router(mission_control_router)
app.include_router(session_brief_router)
app.include_router(actions_router)
app.include_router(workspace_router)
app.include_router(security_router)
app.include_router(understanding_router)
app.include_router(matching_router)
app.include_router(channels_router)
app.include_router(onboarding_router)
app.include_router(drafts_router)
app.include_router(access_router)
app.include_router(telegram_provider_router)
app.include_router(providers_router)
app.include_router(linkedin_provider_router)
app.include_router(brightdata_provider_router)
app.include_router(email_provider_router)
app.include_router(provider_contracts_router)
app.include_router(comm_intake_router)
app.include_router(prompts_router)
app.include_router(resume_builder_router)
app.include_router(submissions.router)
app.include_router(integrations.router)
app.include_router(agents.router)
