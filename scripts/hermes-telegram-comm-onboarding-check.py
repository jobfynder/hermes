from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.sessions.models import ConversationSession

import app.channels.comm_workflow as workflow
import app.channels.service as channel_service
import app.sessions.service as session_service


class FakeVerification:
    confidence = 0.85
    errors: list[str] = []
    missing_fields: list[str] = []
    status = "draft"
    trust_signals = {"draft_object_id": "draft-test-onboarding"}

    def model_dump(self) -> dict:
        return {
            "result_version": "hermes_onboarding_verification_draft_v1",
            "session_id": "session-test",
            "role": "recruiter",
            "status": self.status,
            "full_name": "Test Recruiter",
            "trust_signals": self.trust_signals,
            "missing_fields": self.missing_fields,
            "requires_admin_review": True,
            "confidence": self.confidence,
            "errors": self.errors,
        }


def make_request(message_id: str, text: str) -> ChannelIntakeRequest:
    return ChannelIntakeRequest(
        channel="telegram",
        source_message_id=message_id,
        sender={
            "sender_id": "telegram-test-user",
            "sender_name": "Test Recruiter",
            "username": "test_recruiter",
        },
        conversation_id="telegram-test-chat",
        content_type="text",
        text=text,
        metadata={"telegram_chat_id": "telegram-test-chat"},
    )


def main() -> None:
    sessions: dict[str, ConversationSession] = {}

    def fake_get_or_create_session(
        channel: str,
        external_user_id: str,
        chat_id: str | None = None,
    ) -> ConversationSession:
        key = f"{channel}:{external_user_id}"

        if key not in sessions:
            sessions[key] = ConversationSession(
                session_id="session-test",
                channel=channel,
                external_user_id=external_user_id,
                chat_id=chat_id,
                state="new",
            )

        return sessions[key]

    workflow.get_or_create_session = fake_get_or_create_session
    workflow.create_verification_draft = lambda request: FakeVerification()
    workflow.record_intake = lambda record: None
    workflow.emit_event = lambda event, payload: None

    session_service.save_session = lambda session: session

    channel_service._seen_duplicate_keys.clear()
    channel_service.record_idempotency_key = lambda key: None

    start = workflow.process_comm_channel_intake(
        make_request("test-onboarding-001", "/start")
    )

    assert start.intake_status == "parsed"
    assert start.understanding_result["status"] == "menu_shown"
    assert len(start.outbound_messages) == 1
    assert start.outbound_messages[0].reply_markup is not None
    assert sessions["telegram:telegram-test-user"].state == "menu_shown"

    duplicate_start = workflow.process_comm_channel_intake(
        make_request("test-onboarding-001", "/start")
    )

    assert duplicate_start.intake_status == "duplicate"
    assert duplicate_start.outbound_messages == []

    onboarding_start = workflow.process_comm_channel_intake(
        make_request("test-onboarding-002", "Onboarding: Start")
    )

    assert onboarding_start.intake_status == "parsed"
    assert onboarding_start.understanding_result["state"] == "waiting_for_onboarding"
    assert "Role: Recruiter" in onboarding_start.outbound_messages[0].text
    assert onboarding_start.outbound_messages[0].reply_markup == {
        "remove_keyboard": True
    }

    accidental_switch = workflow.process_comm_channel_intake(
        make_request(
            "test-onboarding-003",
            "Recruiter: Post Job Requirement",
        )
    )

    assert accidental_switch.intake_status == "parsed"
    assert accidental_switch.understanding_result["status"] == (
        "workflow_already_active"
    )
    assert sessions["telegram:telegram-test-user"].state == (
        "waiting_for_onboarding"
    )
    assert sessions["telegram:telegram-test-user"].action == (
        "onboarding_start"
    )
    assert accidental_switch.outbound_messages[0].reply_markup == {
        "remove_keyboard": True
    }

    invalid = workflow.process_comm_channel_intake(
        make_request(
            "test-onboarding-004",
            "Name: Test Recruiter",
        )
    )

    assert invalid.intake_status == "failed"
    assert "onboarding_role_required" in invalid.errors
    assert sessions["telegram:telegram-test-user"].state == "waiting_for_onboarding"

    completed = workflow.process_comm_channel_intake(
        make_request(
            "test-onboarding-005",
            (
                "Role: Recruiter\n"
                "Name: Test Recruiter\n"
                "Company: Jobfynder Test\n"
                "Email: recruiter@jobfynder.test\n"
                "LinkedIn: https://www.linkedin.com/in/test-recruiter\n"
                "Phone: +1 555 555 5555\n"
                "Location: Dallas, TX\n"
                "Focus: US IT Staffing"
            ),
        )
    )

    assert completed.intake_status == "parsed"
    assert completed.document_kind == "recruiter_profile"
    assert completed.draft_object_type == "draft_recruiter_profile"
    assert completed.requires_review is True
    assert completed.understanding_result["draft_id"] == "draft-test-onboarding"
    assert len(completed.outbound_messages) == 1
    assert "sent for verification" in completed.outbound_messages[0].text
    assert sessions["telegram:telegram-test-user"].state == "completed"

    def fake_generic(
        request: ChannelIntakeRequest,
    ) -> ChannelIntakeResponse:
        return ChannelIntakeResponse(
            channel="telegram",
            source_message_id=request.source_message_id,
            intake_status="parsed",
            document_kind="job_description",
            draft_object_type="draft_job_requirement",
            requires_review=True,
            confidence=0.8,
            errors=[],
            duplicate_key=f"telegram:{request.source_message_id}",
        )

    workflow.process_channel_intake = fake_generic

    sessions["telegram:telegram-direct-user"] = ConversationSession(
        session_id="session-direct",
        channel="telegram",
        external_user_id="telegram-direct-user",
        chat_id="telegram-direct-chat",
        state="new",
    )

    direct_request = ChannelIntakeRequest(
        channel="telegram",
        source_message_id="test-direct-001",
        sender={"sender_id": "telegram-direct-user"},
        conversation_id="telegram-direct-chat",
        content_type="text",
        text="Senior Java Developer required with Spring Boot and AWS.",
    )

    direct = workflow.process_comm_channel_intake(direct_request)

    assert direct.document_kind == "job_description"
    assert direct.draft_object_type == "draft_job_requirement"

    print("TELEGRAM_COMM_ONBOARDING_WORKFLOW_PASSED")


if __name__ == "__main__":
    main()
