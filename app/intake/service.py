from pathlib import Path

from app.access.models import ActionAccessRequest
from app.access.service import authorize_action
from app.channels.service import draft_object_for
from app.drafts.service import create_draft_object
from app.intake.models import FileIntakeResult
from app.intake.storage import store_attachment
from app.runtime.events import emit_event
from app.runtime.intake_log import record_intake
from app.understanding.extractors.local_file import extract_local_file
from app.understanding.models import DocumentKind
from app.understanding.service import build_understanding_result


def _confidence_from_understanding(result: dict, document_kind: str) -> float:
    quality = result.get("quality", {})
    confidence = quality.get("confidence")

    if isinstance(confidence, int | float):
        return float(confidence)

    if document_kind == "unknown":
        return 0.2

    return 0.75


def process_file_intake(
    filename: str,
    content: bytes,
    content_type: str | None,
    document_kind: DocumentKind = "unknown",
    channel: str = "generic_api",
    source_message_id: str = "unknown",
    actor_id: str | None = None,
    role: str | None = None,
    action: str | None = None,
) -> FileIntakeResult:
    if actor_id or role or action:
        if not actor_id or not role or not action:
            attachment = store_attachment(
                filename=filename,
                content=content,
                content_type=content_type,
            )
            return FileIntakeResult(
                channel=channel,
                source_message_id=source_message_id,
                document_kind=document_kind,
                intake_status="failed",
                draft_object_type=draft_object_for(document_kind),
                requires_review=True,
                confidence=0.0,
                normalized_skills=[],
                normalized_job_titles=[],
                taxonomy_signals={},
                attachment=attachment,
                extracted_text={},
                understanding_result={
                    "status": "failed",
                    "errors": ["access_context_incomplete"],
                },
                errors=["access_context_incomplete"],
            )

        decision = authorize_action(
            ActionAccessRequest(
                actor_id=actor_id,
                role=role,
                action=action,
                channel=channel,
                metadata={
                    "source_message_id": source_message_id,
                    "filename": filename,
                },
            )
        )

        if decision.status != "allowed":
            attachment = store_attachment(
                filename=filename,
                content=content,
                content_type=content_type,
            )
            return FileIntakeResult(
                channel=channel,
                source_message_id=source_message_id,
                document_kind=document_kind,
                intake_status="failed",
                draft_object_type=draft_object_for(document_kind),
                requires_review=True,
                confidence=0.0,
                normalized_skills=[],
                normalized_job_titles=[],
                taxonomy_signals={},
                attachment=attachment,
                extracted_text={},
                understanding_result={
                    "status": "failed",
                    "errors": [decision.reason or "action_not_allowed"],
                },
                errors=[decision.reason or "action_not_allowed"],
            )

    record_intake(
        {
            "channel": channel,
            "source_message_id": source_message_id,
            "status": "file_received",
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        }
    )
    emit_event(
        "file_intake.received",
        {
            "channel": channel,
            "source_message_id": source_message_id,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        },
    )

    attachment = store_attachment(
        filename=filename,
        content=content,
        content_type=content_type,
    )

    if attachment.status != "stored":
        return FileIntakeResult(
            channel=channel,
            source_message_id=source_message_id,
            document_kind=document_kind,
            intake_status="failed",
            draft_object_type=draft_object_for(document_kind),
            requires_review=True,
            confidence=0.0,
            normalized_skills=[],
            normalized_job_titles=[],
            taxonomy_signals={},
            attachment=attachment,
            extracted_text={},
            understanding_result={
                "status": "failed",
                "errors": attachment.errors,
            },
            errors=attachment.errors,
        )

    extracted = extract_local_file(Path(attachment.storage_ref))
    extracted.filename = filename
    extracted.content_type = content_type

    understanding = build_understanding_result(
        extracted=extracted,
        document_kind=document_kind,
    )

    understanding_dict = understanding.model_dump()
    structured_data = understanding_dict.get("structured_data", {})
    taxonomy_signals = structured_data.get("taxonomy_signals", {})
    normalized_skills = structured_data.get("normalized_skills", [])
    normalized_job_titles = structured_data.get("normalized_job_titles", [])
    confidence = _confidence_from_understanding(
        result=understanding_dict,
        document_kind=document_kind,
    )

    requires_review = confidence < 0.7 or document_kind == "unknown"

    record_intake(
        {
            "channel": channel,
            "source_message_id": source_message_id,
            "status": "file_parsed",
            "document_kind": document_kind,
            "attachment_id": attachment.attachment_id,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
            "confidence": confidence,
            "requires_review": requires_review,
        }
    )
    emit_event(
        "file_intake.parsed",
        {
            "channel": channel,
            "source_message_id": source_message_id,
            "document_kind": document_kind,
            "attachment_id": attachment.attachment_id,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
        },
    )

    draft_type = draft_object_for(document_kind)

    draft = create_draft_object(
        draft_type=draft_type,
        source="file_intake",
        source_ref=attachment.storage_ref,
        channel=channel,
        source_message_id=source_message_id,
        payload={
            "filename": filename,
            "content_type": content_type,
            "document_kind": document_kind,
            "structured_data": structured_data,
        },
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        taxonomy_signals=taxonomy_signals,
        confidence=confidence,
        requires_review=requires_review,
        metadata={
            "attachment_id": attachment.attachment_id,
            "checksum_sha256": attachment.checksum_sha256,
        },
    )

    return FileIntakeResult(
        channel=channel,
        source_message_id=source_message_id,
        document_kind=document_kind,
        intake_status="parsed",
        draft_object_type=draft_type,
        requires_review=requires_review,
        confidence=confidence,
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        taxonomy_signals=taxonomy_signals,
        attachment=attachment,
        extracted_text=extracted.model_dump(),
        understanding_result={
            **understanding_dict,
            "draft_id": draft.draft_id,
        },
        errors=[],
    )
