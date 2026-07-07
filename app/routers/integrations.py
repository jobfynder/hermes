from fastapi import APIRouter

from app.integrations.models import (
    IntegrationEnvelope,
    IntegrationHealthResponse,
    IntegrationNormalizedEvent,
)
from app.integrations.service import (
    get_integration_health,
    normalize_integration_event,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("/health", response_model=IntegrationHealthResponse)
def integrations_health() -> IntegrationHealthResponse:
    return get_integration_health()


@router.post("/events/normalize", response_model=IntegrationNormalizedEvent)
def normalize_event(
    envelope: IntegrationEnvelope,
) -> IntegrationNormalizedEvent:
    return normalize_integration_event(envelope)
