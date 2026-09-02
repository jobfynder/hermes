from typing import Any

from pydantic import BaseModel

from fastapi import APIRouter, Depends

from app.assistant.service import answer_query
from app.security.rbac import require_permission

router = APIRouter(prefix="/assistant", tags=["Assistant"])


class ConversationTurn(BaseModel):
    role: str
    content: str


class AssistantQueryRequest(BaseModel):
    question: str
    history: list[ConversationTurn] = []


class AssistantQueryResult(BaseModel):
    answer: str
    tool_used: str | None = None
    data: dict[str, Any] | None = None


@router.post("/query", response_model=AssistantQueryResult)
def assistant_query(
    body: AssistantQueryRequest,
    _user: dict = Depends(require_permission("drafts:read")),
) -> AssistantQueryResult:
    """Natural-language question about taxonomy size, the review-candidate
    backlog, daily triage activity, LLM cost, or parsing quality -- see
    app/assistant/service.py for how the question gets routed to a safe,
    read-only data lookup rather than an open-ended query.
    """
    result = answer_query(
        body.question,
        history=[turn.model_dump() for turn in body.history],
    )
    return AssistantQueryResult(**result)
