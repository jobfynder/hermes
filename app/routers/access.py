from fastapi import APIRouter

from app.access.models import ActionAccessDecision, ActionAccessRequest
from app.access.registry import ROLE_ACTIONS
from app.access.service import authorize_action

router = APIRouter(prefix="/access", tags=["Access"])


@router.get("/actions")
def get_action_registry() -> dict:
    return {
        "result_version": "hermes_role_action_registry_v1",
        "roles": ROLE_ACTIONS,
    }


@router.post("/authorize", response_model=ActionAccessDecision)
def authorize(request: ActionAccessRequest) -> ActionAccessDecision:
    return authorize_action(request)
