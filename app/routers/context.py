from fastapi import APIRouter, Depends

from app.context.candidate_card import build_candidate_card
from app.context.conversation_context import compress_conversation
from app.context.job_card import build_job_card
from app.context.models import (
    CandidateCardBuildRequest,
    ConversationCompressRequest,
    JobCardBuildRequest,
    RelationshipCardBuildRequest,
)
from app.context.relationship_card import build_relationship_card
from app.contracts.envelope import HermesCapabilityEnvelope, build_envelope
from app.security.rbac import require_permission

router = APIRouter(prefix="/context", tags=["context"])


@router.post("/candidate-card/build", response_model=HermesCapabilityEnvelope)
def context_build_candidate_card(
    request: CandidateCardBuildRequest,
    _user: dict = Depends(require_permission("context:build")),
) -> HermesCapabilityEnvelope:
    card = build_candidate_card(request)
    return build_envelope(
        capability="hermes.context.build_candidate_card",
        structured_data=card.model_dump(),
        confidence=card.source_confidence,
        llm_required=False,
    )


@router.post("/job-card/build", response_model=HermesCapabilityEnvelope)
def context_build_job_card(
    request: JobCardBuildRequest,
    _user: dict = Depends(require_permission("context:build")),
) -> HermesCapabilityEnvelope:
    card = build_job_card(request)
    return build_envelope(
        capability="hermes.context.build_job_card",
        structured_data=card.model_dump(),
        confidence=card.source_confidence,
        llm_required=False,
    )


@router.post("/relationship-card/build", response_model=HermesCapabilityEnvelope)
def context_build_relationship_card(
    request: RelationshipCardBuildRequest,
    _user: dict = Depends(require_permission("context:build")),
) -> HermesCapabilityEnvelope:
    card = build_relationship_card(request)
    return build_envelope(
        capability="hermes.context.build_relationship_card",
        structured_data=card.model_dump(),
        llm_required=False,
    )


@router.post("/conversation/compress", response_model=HermesCapabilityEnvelope)
def context_compress_conversation(
    request: ConversationCompressRequest,
    _user: dict = Depends(require_permission("context:build")),
) -> HermesCapabilityEnvelope:
    context = compress_conversation(request)
    return build_envelope(
        capability="hermes.context.compress_conversation",
        structured_data=context.model_dump(),
        llm_required=False,
    )
