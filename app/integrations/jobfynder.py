from typing import Any

from app.integrations.models import IntegrationEnvelope
from app.submission_intelligence.models import (
    SubmissionConsultantSnapshot,
    SubmissionEvent,
    SubmissionIntelligenceRequest,
    SubmissionParty,
    SubmissionRelationshipSnapshot,
    SubmissionRequirementSnapshot,
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _party(data: dict[str, Any]) -> SubmissionParty:
    return SubmissionParty(**_dict(data))


def build_submission_request_from_jobfynder_event(
    envelope: IntegrationEnvelope,
) -> SubmissionIntelligenceRequest:
    payload = _dict(envelope.payload)

    requirement = SubmissionRequirementSnapshot(**_dict(payload.get("requirement")))
    consultant = SubmissionConsultantSnapshot(**_dict(payload.get("consultant")))

    relationship_data = _dict(payload.get("relationship"))
    relationship = SubmissionRelationshipSnapshot(
        recruiter=_party(relationship_data["recruiter"]) if "recruiter" in relationship_data else None,
        bench_sales_recruiter=_party(relationship_data["bench_sales_recruiter"]) if "bench_sales_recruiter" in relationship_data else None,
        employer=_party(relationship_data["employer"]) if "employer" in relationship_data else None,
        vendor=_party(relationship_data["vendor"]) if "vendor" in relationship_data else None,
        relationship_strength=relationship_data.get("relationship_strength"),
        trust_level=relationship_data.get("trust_level"),
    )

    event = None
    event_data = _dict(payload.get("event"))
    if event_data:
        event = SubmissionEvent(
            event_type=event_data.get("event_type", "note_added"),
            from_stage=event_data.get("from_stage"),
            to_stage=event_data.get("to_stage"),
            actor=_party(_dict(event_data.get("actor"))),
            note=event_data.get("note"),
            metadata=_dict(event_data.get("metadata")),
        )

    return SubmissionIntelligenceRequest(
        submission_id=payload.get("submission_id"),
        current_stage=payload.get("current_stage", "discovered"),
        event=event,
        requirement=requirement,
        consultant=consultant,
        relationship=relationship,
        match_result=_dict(payload.get("match_result")),
        parser_result=_dict(payload.get("parser_result")),
        taxonomy_context=_dict(payload.get("taxonomy_context")),
        existing_submission_keys=[
            str(item) for item in _list(payload.get("existing_submission_keys"))
        ],
    )
