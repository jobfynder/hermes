from fastapi import APIRouter

from app.config import HERMES_ENV, HERMES_SERVICE_NAME, HERMES_VERSION

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "service": HERMES_SERVICE_NAME,
        "version": HERMES_VERSION,
        "environment": HERMES_ENV,
    }
