from app.channels.models import (
    ChannelIntakeRequest,
    ChannelIntakeResponse,
    ChannelOutboundMessage,
    DocumentKind,
)
from app.channels.service import (
    build_duplicate_key,
    is_duplicate_key,
    process_channel_intake,
    remember_duplicate_key,
)
from app.onboarding.models import OnboardingVerificationDraftRequest
from app.onboarding.service import create_verification_draft
from app.onboarding.text_parser import (
    parse_key_value_onboarding_text,
    role_from_onboarding_data,
)
from app.providers.telegram.messages import (
    build_start_menu,
    map_telegram_text_to_action,
)
from app.runtime.events import emit_event
from app.runtime.intake_log import record_intake
from app.sessions.service import (
    complete_session,
    get_or_create_session,
    reset_to_menu,
    start_waiting_for_action,
)


BUSINESS_WAITING_STATES = {
    "waiting_for_hotlist",
    "waiting_for_candidate",
    "waiting_for_job_requirement",
}


def _conversation_id(request: ChannelIntakeRequest) -> str:
    return str(
        request.conversation_id
        or request.metadata.get("telegram_chat_id")
        or request.sender.sender_id
        or "unknown"
    )


def _external_user_id(request: ChannelIntakeRequest) -> str:
    return str(
        request.sender.sender_id
        or request.actor_id
        or request.conversation_id
        or "unknown"
    )


def _outbound(
    request: ChannelIntakeRequest,
    text: str,
    *,
    reply_markup: dict | None = None,
    status: str,
    metadata: dict | None = None,
) -> ChannelOutboundMessage:
    return ChannelOutboundMessage(
        channel="telegram",
        conversation_id=_conversation_id(request),
        text=text,
        reply_markup=reply_markup,
        metadata={
            "workflow": "telegram_onboarding",
            "status": status,
            **(metadata or {}),
        },
    )


def _duplicate_response(
    request: ChannelIntakeRequest,
    duplicate_key: str,
) -> ChannelIntakeResponse:
    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "duplicate",
            "workflow": "telegram_session",
        }
    )
    emit_event(
        "telegram.workflow.duplicate",
        {
            "duplicate_key": duplicate_key,
            "source_message_id": request.source_message_id,
        },
    )

    return ChannelIntakeResponse(
        channel="telegram",
        source_message_id=request.source_message_id,
        intake_status="duplicate",
        document_kind="plain_message",
        requires_review=False,
        confidence=1.0,
        errors=["duplicate_message"],
        duplicate_key=duplicate_key,
        understanding_result={
            "status": "duplicate",
            "workflow": "telegram_session",
        },
    )


def _claim_workflow_request(
    request: ChannelIntakeRequest,
) -> tuple[bool, str]:
    duplicate_key = build_duplicate_key(request)

    if is_duplicate_key(duplicate_key):
        return False, duplicate_key

    remember_duplicate_key(duplicate_key)

    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "received",
            "workflow": "telegram_session",
            "conversation_id": _conversation_id(request),
            "external_user_id": _external_user_id(request),
        }
    )
    emit_event(
        "telegram.workflow.received",
        {
            "duplicate_key": duplicate_key,
            "source_message_id": request.source_message_id,
            "conversation_id": _conversation_id(request),
        },
    )

    return True, duplicate_key


def _control_response(
    request: ChannelIntakeRequest,
    *,
    duplicate_key: str,
    session,
    status: str,
    outbound: ChannelOutboundMessage,
    intake_status: str = "parsed",
    errors: list[str] | None = None,
    confidence: float = 1.0,
) -> ChannelIntakeResponse:
    return ChannelIntakeResponse(
        channel="telegram",
        source_message_id=request.source_message_id,
        intake_status=intake_status,
        document_kind="plain_message",
        draft_object_type=None,
        requires_review=False,
        confidence=confidence,
        errors=errors or [],
        duplicate_key=duplicate_key,
        outbound_messages=[outbound],
        understanding_result={
            "status": status,
            "workflow": "telegram_session",
            "session_id": session.session_id,
            "state": session.state,
            "role": session.role,
            "action": session.action,
            "expected_input": session.expected_input,
        },
    )


def _onboarding_prompt() -> str:
    return (
        "Please send your onboarding details in one message using this format:\n\n"
        "Role: Recruiter\n"
        "Name: Your Full Name\n"
        "Company: Company Name\n"
        "Email: work@company.com\n"
        "LinkedIn: https://www.linkedin.com/in/your-profile\n"
        "Phone: +1 555 555 5555\n"
        "Location: City, State\n"
        "Focus: US IT Staffing\n\n"
        "Accepted roles: Recruiter, BSR, or Consultant.\n"
        "Company, work email, and LinkedIn are important for recruiter and BSR verification."
    )


def _profile_document_kind(role: str) -> DocumentKind:
    if role == "bench_sales":
        return "bench_sales_profile"
    if role == "recruiter":
        return "recruiter_profile"
    return "consultant_profile"


def _profile_draft_type(role: str) -> str:
    if role == "bench_sales":
        return "draft_bench_sales_profile"
    if role == "recruiter":
        return "draft_recruiter_profile"
    return "draft_consultant_profile"


def _process_onboarding_input(
    request: ChannelIntakeRequest,
    session,
) -> ChannelIntakeResponse:
    claimed, duplicate_key = _claim_workflow_request(request)

    if not claimed:
        return _duplicate_response(request, duplicate_key)

    onboarding_data = parse_key_value_onboarding_text(request.text or "")
    role = role_from_onboarding_data(
        onboarding_data,
        fallback_role=session.role,
    )

    required_errors: list[str] = []

    if not onboarding_data.get("full_name"):
        required_errors.append("onboarding_full_name_required")

    if role == "unknown":
        required_errors.append("onboarding_role_required")

    if required_errors:
        outbound = _outbound(
            request,
            (
                "I could not complete onboarding because your name or role is missing.\n\n"
                + _onboarding_prompt()
            ),
            status="onboarding_input_invalid",
            metadata={"errors": required_errors},
        )

        return _control_response(
            request,
            duplicate_key=duplicate_key,
            session=session,
            status="onboarding_input_invalid",
            outbound=outbound,
            intake_status="failed",
            errors=required_errors,
            confidence=0.0,
        )

    verification = create_verification_draft(
        OnboardingVerificationDraftRequest(
            session_id=session.session_id,
            role=role,
            full_name=onboarding_data["full_name"],
            company_name=onboarding_data.get("company_name"),
            company_email=onboarding_data.get("company_email"),
            phone=onboarding_data.get("phone"),
            linkedin_url=onboarding_data.get("linkedin_url"),
            location=onboarding_data.get("location"),
            staffing_focus=onboarding_data.get("staffing_focus"),
            notes=onboarding_data.get("notes"),
            channel="telegram",
            metadata={
                "telegram_user_id": _external_user_id(request),
                "telegram_chat_id": _conversation_id(request),
                "telegram_username": request.sender.username,
                "sender_name": request.sender.sender_name,
                "source_message_id": request.source_message_id,
            },
        )
    )

    complete_session(session)

    draft_id = verification.trust_signals.get("draft_object_id")
    missing_fields = verification.missing_fields

    reply_text = (
        f"Thank you, {onboarding_data['full_name']}.\n\n"
        "Your Jobfynder onboarding profile has been created and sent for verification."
    )

    if missing_fields:
        reply_text += (
            "\n\nAdditional review is required because these fields are missing: "
            + ", ".join(missing_fields)
            + "."
        )
    else:
        reply_text += "\n\nYour profile is now pending administrator approval."

    menu = build_start_menu()
    outbound = _outbound(
        request,
        reply_text,
        reply_markup=menu["reply_markup"],
        status="onboarding_verification_pending",
        metadata={
            "draft_id": draft_id,
            "role": role,
            "missing_fields": missing_fields,
        },
    )

    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "onboarding_verification_draft_created",
            "session_id": session.session_id,
            "role": role,
            "draft_id": draft_id,
            "missing_fields": missing_fields,
            "confidence": verification.confidence,
        }
    )
    emit_event(
        "telegram.onboarding.verification_draft.created",
        {
            "session_id": session.session_id,
            "role": role,
            "draft_id": draft_id,
        },
    )

    return ChannelIntakeResponse(
        channel="telegram",
        source_message_id=request.source_message_id,
        intake_status="parsed",
        document_kind=_profile_document_kind(role),
        draft_object_type=_profile_draft_type(role),
        requires_review=True,
        confidence=verification.confidence,
        errors=verification.errors,
        duplicate_key=duplicate_key,
        outbound_messages=[outbound],
        understanding_result={
            **verification.model_dump(),
            "workflow": "telegram_onboarding",
            "draft_id": draft_id,
            "conversation_session_id": session.session_id,
        },
    )


def _process_waiting_business_input(
    request: ChannelIntakeRequest,
    session,
) -> ChannelIntakeResponse:
    enriched_request = request.model_copy(
        update={
            "actor_id": f"telegram:{_external_user_id(request)}",
            "role": session.role,
            "action": session.action,
            "metadata": {
                **request.metadata,
                "telegram_flow": "business_input",
                "session_id": session.session_id,
                "conversation_state": session.state,
            },
        }
    )

    result = process_channel_intake(enriched_request)

    if result.intake_status not in {"duplicate", "failed"}:
        complete_session(session)

        result.outbound_messages = [
            _outbound(
                request,
                (
                    f"Jobfynder received your {result.document_kind}."
                    + (
                        f"\nDraft created: {result.draft_object_type}"
                        if result.draft_object_type
                        else ""
                    )
                ),
                status="business_input_processed",
                metadata={
                    "document_kind": result.document_kind,
                    "draft_object_type": result.draft_object_type,
                },
            )
        ]

    return result


def process_telegram_comm_intake(
    request: ChannelIntakeRequest,
) -> ChannelIntakeResponse:
    external_user_id = _external_user_id(request)
    conversation_id = _conversation_id(request)

    session = get_or_create_session(
        channel="telegram",
        external_user_id=external_user_id,
        chat_id=conversation_id,
    )

    mapped = map_telegram_text_to_action(request.text or "")

    if mapped:
        claimed, duplicate_key = _claim_workflow_request(request)

        if not claimed:
            return _duplicate_response(request, duplicate_key)

        if mapped.get("type") == "menu":
            transition = reset_to_menu(session)
            menu = build_start_menu()

            return _control_response(
                request,
                duplicate_key=duplicate_key,
                session=transition.session,
                status="menu_shown",
                outbound=_outbound(
                    request,
                    menu["text"],
                    reply_markup=menu["reply_markup"],
                    status="menu_shown",
                ),
            )

        if mapped.get("type") in {"action", "onboarding"}:
            transition = start_waiting_for_action(
                session=session,
                role=mapped.get("role") or "unknown",
                action=mapped.get("action") or "onboarding_start",
            )

            prompt = (
                _onboarding_prompt()
                if transition.session.action == "onboarding_start"
                else transition.response_text
            )

            return _control_response(
                request,
                duplicate_key=duplicate_key,
                session=transition.session,
                status="waiting_for_input",
                outbound=_outbound(
                    request,
                    prompt or "Please send the requested information.",
                    status="waiting_for_input",
                    metadata={
                        "action": transition.session.action,
                        "expected_input": transition.session.expected_input,
                    },
                ),
            )

    if session.state == "waiting_for_onboarding":
        return _process_onboarding_input(request, session)

    if session.state in BUSINESS_WAITING_STATES:
        return _process_waiting_business_input(request, session)

    # Preserve the production behavior that allows a user to directly paste
    # a job description, resume, hotlist, or profile without opening the menu.
    return process_channel_intake(request)


def process_comm_channel_intake(
    request: ChannelIntakeRequest,
) -> ChannelIntakeResponse:
    if request.channel == "telegram":
        return process_telegram_comm_intake(request)

    return process_channel_intake(request)
