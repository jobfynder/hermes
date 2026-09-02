from typing import Any

from fastapi import APIRouter, Depends

from app.reporting.service import (
    get_ai_dependency_report,
    get_candidate_queue_health,
    get_classification_report,
    get_dashboard_overview,
    get_ingestion_health,
    get_llm_cost_trend,
    get_parsing_quality,
    get_recruitment_intelligence,
    get_review_queue_report,
    get_sender_intelligence,
    get_signature_quality_report,
    get_taxonomy_overview,
    get_triage_activity,
)
from app.security.rbac import require_permission

router = APIRouter(prefix="/reports", tags=["Reporting"])


@router.get("/overview")
def dashboard_overview(
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    """Everything the dashboard page needs in one round trip -- taxonomy
    size/growth, candidate queue health, recent triage activity, LLM
    cost trend, and parsing quality. See app/reporting/service.py.
    """
    return get_dashboard_overview()


@router.get("/taxonomy")
def taxonomy_overview(
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_taxonomy_overview()


@router.get("/queue-health")
def queue_health(
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_candidate_queue_health()


@router.get("/triage-activity")
def triage_activity(
    days: int = 14,
    _user: dict = Depends(require_permission("drafts:read")),
) -> list[dict[str, Any]]:
    return get_triage_activity(days=days)


@router.get("/llm-cost")
def llm_cost(
    days: int = 30,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_llm_cost_trend(days=days)


@router.get("/parsing-quality")
def parsing_quality(
    days: int = 7,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_parsing_quality(days=days)


@router.get("/ingestion-health")
def ingestion_health(
    days: int = 7,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_ingestion_health(days=days)


@router.get("/classification")
def classification_report(
    days: int = 7,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_classification_report(days=days)


@router.get("/ai-dependency")
def ai_dependency_report(
    days: int = 7,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_ai_dependency_report(days=days)


@router.get("/review-queue")
def review_queue_report(
    days: int = 7,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_review_queue_report(days=days)


@router.get("/signature-quality")
def signature_quality_report(
    days: int = 30,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_signature_quality_report(days=days)


@router.get("/recruitment-intelligence")
def recruitment_intelligence(
    days: int = 30,
    limit: int = 15,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_recruitment_intelligence(days=days, limit=limit)


@router.get("/sender-intelligence")
def sender_intelligence(
    days: int = 30,
    limit: int = 15,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict[str, Any]:
    return get_sender_intelligence(days=days, limit=limit)
