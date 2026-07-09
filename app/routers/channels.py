from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.config import HERMES_TELEGRAM_WEBHOOK_SECRET
from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.channels.adapters.registry import get_channel_adapter, list_channel_adapters
from app.channels.registry import get_supported_channels
from app.channels.service import process_channel_intake
from app.intake.service import process_file_intake
from app.onboarding.models import OnboardingVerificationDraftRequest
from app.onboarding.service import create_verification_draft
from app.onboarding.text_parser import parse_key_value_onboarding_text, role_from_onboarding_data
from app.providers.telegram.messages import (
    build_blocked_free_chat_message,
    build_start_menu,
    map_telegram_text_to_action,
)
from app.providers.telegram.service import send_telegram_message, telegram_download_file
from app.sessions.service import (
    complete_session,
    get_or_create_session,
    handle_business_input,
    reset_to_menu,
    start_waiting_for_action,
)

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.get("/health")
def channels_health() -> dict[str, str]:
    return {
        "status": "ok",
        "module": "HERMES-450",
        "component": "channel_intake",
    }


@router.get("/supported")
def supported_channels() -> dict[str, Any]:
    result = get_supported_channels()
    result["adapters"] = list_channel_adapters()
    return result


@router.post("/intake", response_model=ChannelIntakeResponse)
def channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    adapter = get_channel_adapter(request.channel)
    normalized = adapter.normalize(request.model_dump())
    return process_channel_intake(normalized)


@router.post("/telegram/webhook", response_model=ChannelIntakeResponse)
def telegram_webhook(
    payload: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> ChannelIntakeResponse:
    if HERMES_TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != HERMES_TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=403,
                detail="Invalid Telegram webhook secret",
            )

    message = payload.get("message", {})
    chat = message.get("chat", {})
    text = message.get("text") or ""
    chat_id = chat.get("id")

    sender = message.get("from", {})
    external_user_id = str(sender.get("id") or "unknown")
    session = get_or_create_session(
        channel="telegram",
        external_user_id=external_user_id,
        chat_id=str(chat_id) if chat_id is not None else None,
    )

    document = message.get("document")
    if document:
        sender = message.get("from", {})
        external_user_id = str(sender.get("id") or "unknown")
        session = get_or_create_session(
            channel="telegram",
            external_user_id=external_user_id,
            chat_id=str(chat_id) if chat_id is not None else None,
        )
        transition = handle_business_input(session)

        if not transition.should_parse:
            blocked = build_blocked_free_chat_message()
            if chat_id is not None:
                send_telegram_message(
                    chat_id=chat_id,
                    text=blocked["text"],
                    reply_markup=blocked["reply_markup"],
                )

            return ChannelIntakeResponse(
                channel="telegram",
                source_message_id=str(message.get("message_id") or payload.get("update_id")),
                intake_status="failed",
                document_kind="plain_message",
                draft_object_type="draft_channel_note",
                requires_review=False,
                confidence=1.0,
                errors=["unexpected_file_without_active_workflow"],
                duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
                understanding_result={
                    "status": "blocked_file_without_workflow",
                    "session_id": session.session_id,
                    "should_parse": False,
                },
            )

        downloaded = telegram_download_file(document.get("file_id"))

        if downloaded.get("status") != "downloaded":
            return ChannelIntakeResponse(
                channel="telegram",
                source_message_id=str(message.get("message_id") or payload.get("update_id")),
                intake_status="failed",
                document_kind="unknown",
                draft_object_type="draft_channel_note",
                requires_review=True,
                confidence=0.0,
                errors=[downloaded.get("reason", "telegram_file_download_failed")],
                duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
                understanding_result=downloaded,
            )

        document_kind = "unknown"
        if session.action == "post_hotlist":
            document_kind = "unknown"
        elif session.action == "add_candidate":
            document_kind = "resume"
        elif session.action == "post_job_requirement":
            document_kind = "job_description"

        result = process_file_intake(
            filename=document.get("file_name") or downloaded["filename"],
            content=downloaded["content"],
            content_type=document.get("mime_type") or downloaded.get("content_type"),
            document_kind=document_kind,
            channel="telegram",
            source_message_id=str(message.get("message_id") or payload.get("update_id")),
            actor_id=f"telegram:{external_user_id}",
            role=session.role,
            action=session.action,
        )
        complete_session(session)
        return result


    mapped = map_telegram_text_to_action(text)

    if mapped and mapped.get("type") == "menu":
        transition = reset_to_menu(session)
        menu = build_start_menu()
        if chat_id is not None:
            send_telegram_message(
                chat_id=chat_id,
                text=menu["text"],
                reply_markup=menu["reply_markup"],
            )

        return ChannelIntakeResponse(
            channel="telegram",
            source_message_id=str(message.get("message_id") or payload.get("update_id")),
            intake_status="parsed",
            document_kind="plain_message",
            draft_object_type="draft_channel_note",
            requires_review=False,
            confidence=1.0,
            errors=[],
            duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
            understanding_result={
                "status": "menu_shown",
                "session_id": transition.session.session_id,
                "should_parse": False,
            },
        )

    if mapped and mapped.get("type") in {"action", "onboarding"}:
        transition = start_waiting_for_action(
            session=session,
            role=mapped.get("role") or "unknown",
            action=mapped.get("action") or "onboarding_start",
        )
        if chat_id is not None and transition.response_text:
            send_telegram_message(
                chat_id=chat_id,
                text=transition.response_text,
                reply_markup=None,
            )

        return ChannelIntakeResponse(
            channel="telegram",
            source_message_id=str(message.get("message_id") or payload.get("update_id")),
            intake_status="parsed",
            document_kind="plain_message",
            draft_object_type="draft_channel_note",
            requires_review=False,
            confidence=1.0,
            errors=[],
            duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
            understanding_result={
                "status": "waiting_for_input",
                "session_id": transition.session.session_id,
                "state": transition.session.state,
                "role": transition.session.role,
                "action": transition.session.action,
                "expected_input": transition.session.expected_input,
                "should_parse": False,
            },
        )

    transition = handle_business_input(session)

    if not transition.should_parse:
        blocked = build_blocked_free_chat_message()
        if chat_id is not None:
            send_telegram_message(
                chat_id=chat_id,
                text=blocked["text"],
                reply_markup=blocked["reply_markup"],
            )

        return ChannelIntakeResponse(
            channel="telegram",
            source_message_id=str(message.get("message_id") or payload.get("update_id")),
            intake_status="failed",
            document_kind="plain_message",
            draft_object_type="draft_channel_note",
            requires_review=False,
            confidence=1.0,
            errors=["unexpected_free_chat"],
            duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
            understanding_result={
                "status": "blocked_free_chat",
                "session_id": session.session_id,
                "should_parse": False,
            },
        )

    if session.action == "onboarding_start":
        onboarding_data = parse_key_value_onboarding_text(text)
        role = role_from_onboarding_data(
            onboarding_data,
            fallback_role=session.role,
        )

        if "full_name" not in onboarding_data:
            return ChannelIntakeResponse(
                channel="telegram",
                source_message_id=str(message.get("message_id") or payload.get("update_id")),
                intake_status="failed",
                document_kind="plain_message",
                draft_object_type="draft_channel_note",
                requires_review=False,
                confidence=0.0,
                errors=["onboarding_full_name_required"],
                duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
                understanding_result={
                    "status": "onboarding_input_invalid",
                    "required_format": [
                        "Role: BSR",
                        "Name: Your Name",
                        "Company: Company Name",
                        "Email: work@example.com",
                        "LinkedIn: https://www.linkedin.com/in/...",
                    ],
                },
            )

        verification = create_verification_draft(
            OnboardingVerificationDraftRequest(
                session_id=session.session_id,
                role=role,
                full_name=onboarding_data.get("full_name"),
                company_name=onboarding_data.get("company_name"),
                company_email=onboarding_data.get("company_email"),
                phone=onboarding_data.get("phone"),
                linkedin_url=onboarding_data.get("linkedin_url"),
                location=onboarding_data.get("location"),
                staffing_focus=onboarding_data.get("staffing_focus"),
                notes=onboarding_data.get("notes"),
                channel="telegram",
                metadata={
                    "telegram_user_id": external_user_id,
                    "telegram_chat_id": chat_id,
                },
            )
        )
        complete_session(session)

        return ChannelIntakeResponse(
            channel="telegram",
            source_message_id=str(message.get("message_id") or payload.get("update_id")),
            intake_status="parsed",
            document_kind="bench_sales_profile" if role == "bench_sales" else (
                "recruiter_profile" if role == "recruiter" else "consultant_profile"
            ),
            draft_object_type="draft_bench_sales_profile" if role == "bench_sales" else (
                "draft_recruiter_profile" if role == "recruiter" else "draft_consultant_profile"
            ),
            requires_review=True,
            confidence=verification.confidence,
            errors=verification.errors,
            duplicate_key=f"telegram:{message.get('message_id') or payload.get('update_id')}",
            understanding_result=verification.model_dump(),
            taxonomy_signals={},
            normalized_skills=[],
            normalized_job_titles=[],
        )

    adapter = get_channel_adapter("telegram")
    normalized = adapter.normalize(payload)
    normalized.actor_id = f"telegram:{external_user_id}"
    normalized.role = session.role
    normalized.action = session.action
    normalized.metadata = {
        **normalized.metadata,
        "telegram_flow": "business_input",
        "session_id": session.session_id,
        "conversation_state": session.state,
    }

    result = process_channel_intake(normalized)
    complete_session(session)
    return result



@router.post("/intake/file")
async def channel_file_intake(
    file: UploadFile = File(...),
    channel: str = Form("generic_api"),
    source_message_id: str = Form(...),
    document_kind: str = Form("unknown"),
    actor_id: str | None = Form(None),
    role: str | None = Form(None),
    action: str | None = Form(None),
):
    content = await file.read()

    return process_file_intake(
        filename=file.filename or "uploaded.txt",
        content=content,
        content_type=file.content_type,
        document_kind=document_kind,
        channel=channel,
        source_message_id=source_message_id,
        actor_id=actor_id,
        role=role,
        action=action,
    )
