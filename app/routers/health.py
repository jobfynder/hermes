from fastapi import APIRouter, Depends

from app.config import HERMES_ENV, HERMES_SERVICE_NAME, HERMES_VERSION
from app.runtime.cache import cache_stats
from app.security.rbac import require_permission

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "service": HERMES_SERVICE_NAME,
        "version": HERMES_VERSION,
        "environment": HERMES_ENV,
    }


@router.get("/runtime/cache/stats")
def runtime_cache_stats(
    _user: dict = Depends(require_permission("runtime:read")),
):
    return cache_stats()
