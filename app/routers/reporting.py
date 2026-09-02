from typing import Any

from fastapi import APIRouter, Depends

from app.reporting.service import (
    get_candidate_queue_health,
    get_dashboard_overview,
    get_llm_cost_trend,
    get_parsing_quality,
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
