from app.security.rbac import require_admin_permission
from fastapi import APIRouter, Depends

from app.providers.models import ProviderHealth
from app.providers.registry import get_all_provider_health, get_provider_health

router = APIRouter(prefix="/providers", tags=["Providers"])


@router.get("", response_model=list[ProviderHealth])
def list_providers(_principal: dict = Depends(require_admin_permission("runtime:read"))) -> list[ProviderHealth]:
    return get_all_provider_health()


@router.get("/status")
def provider_status_summary(_principal: dict = Depends(require_admin_permission("runtime:read"))) -> dict:
    providers = get_all_provider_health()

    return {
        "result_version": "hermes_provider_status_v1",
        "configured": [
            provider.provider
            for provider in providers
            if provider.status == "configured"
        ],
        "contracts": [
            provider.provider
            for provider in providers
            if provider.status == "contract"
        ],
        "failed": [
            provider.provider
            for provider in providers
            if provider.status == "failed"
        ],
        "providers": [provider.model_dump() for provider in providers],
    }


@router.get("/{provider}", response_model=ProviderHealth)
def read_provider(provider: str, _principal: dict = Depends(require_admin_permission("runtime:read"))) -> ProviderHealth:
    return get_provider_health(provider)
