import json

from fastapi.testclient import TestClient

import app.channels.comm_workflow as workflow
import app.channels.service as channel_service
import app.routers.comm_intake as comm_router
import app.sessions.service as session_service
from app.main import app
from app.sessions.models import ConversationSession


class FakeVerification:
    confidence = 0.85
    errors: list[str] = []
    missing_fields: list[str] = []
    status = "draft"
    trust_signals = {"draft_object_id": "draft-route-test"}

    def model_dump(self) -> dict:
        return {
            "result_version": "hermes_onboarding_verification_draft_v1",
            "session_id": "route-session-test",
            "role": "recruiter",
            "status": self.status,
            "full_name": "Route Test Recruiter",
            "company_name": "Jobfynder Test",
            "company_email": "recruiter@jobfynder.test",
            "phone": "+1 555 555 5555",
            "linkedin_url": "https://www.linkedin.com/in/route-test",
            "location": "Dallas, TX",
            "staffing_focus": "US IT Staffing",
            "trust_signals": self.trust_signals,
            "missing_fields": self.missing_fields,
            "requires_admin_review": True,
            "confidence": self.confidence,
            "errors": self.errors,
        }


def payload(message_id: str, text: str) -> dict:
    return {
        "channel": "telegram",
        "source_message_id": message_id,
        "actor_id": "telegram:route-test-user",
        "sender": {
            "sender_id": "route-test-user",
            "sender_name": "Route Test Recruiter",
            "username": "route_test_recruiter",
        },
        "conversation_id": "route-test-chat",
        "content_type": "text",
        "text": text,
        "metadata": {
            "telegram_chat_id": "route-test-chat",
            "telegram_update_id": message_id,
        },
    }


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
                session_id="route-session-test",
                channel=channel,
                external_user_id=external_user_id,
                chat_id=chat_id,
                state="new",
            )

        return sessions[key]

    async def fake_require_comm_signature(request):
        return await request.body()

    workflow.get_or_create_session = fake_get_or_create_session
    workflow.create_verification_draft = lambda request: FakeVerification()
    workflow.record_intake = lambda record: None
    workflow.emit_event = lambda event, body: None

    session_service.save_session = lambda session: session

    channel_service._seen_duplicate_keys.clear()
    channel_service.record_idempotency_key = lambda key: None

    comm_router.require_comm_signature = fake_require_comm_signature

    client = TestClient(app)

    start = client.post(
        "/internal/comm/intake",
        content=json.dumps(payload("route-001", "/start")),
        headers={"content-type": "application/json"},
    )

    assert start.status_code == 200, start.text
    start_body = start.json()

    assert start_body["intake_status"] == "parsed"
    assert start_body["understanding_result"]["status"] == "menu_shown"
    assert start_body["outbound_messages"][0]["conversation_id"] == "route-test-chat"
    assert start_body["outbound_messages"][0]["reply_markup"]["keyboard"]

    onboarding_start = client.post(
        "/internal/comm/intake",
        content=json.dumps(
            payload("route-002", "Onboarding: Start")
        ),
        headers={"content-type": "application/json"},
    )

    assert onboarding_start.status_code == 200, onboarding_start.text
    onboarding_start_body = onboarding_start.json()

    assert onboarding_start_body["intake_status"] == "parsed"
    assert (
        onboarding_start_body["understanding_result"]["state"]
        == "waiting_for_onboarding"
    )
    assert (
        "Role: Recruiter"
        in onboarding_start_body["outbound_messages"][0]["text"]
    )

    completed = client.post(
        "/internal/comm/intake",
        content=json.dumps(
            payload(
                "route-003",
                (
                    "Role: Recruiter\n"
                    "Name: Route Test Recruiter\n"
                    "Company: Jobfynder Test\n"
                    "Email: recruiter@jobfynder.test\n"
                    "LinkedIn: https://www.linkedin.com/in/route-test\n"
                    "Phone: +1 555 555 5555\n"
                    "Location: Dallas, TX\n"
                    "Focus: US IT Staffing"
                ),
            )
        ),
        headers={"content-type": "application/json"},
    )

    assert completed.status_code == 200, completed.text
    completed_body = completed.json()

    assert completed_body["intake_status"] == "parsed"
    assert completed_body["document_kind"] == "recruiter_profile"
    assert completed_body["draft_object_type"] == "draft_recruiter_profile"
    assert completed_body["requires_review"] is True
    assert completed_body["understanding_result"]["draft_id"] == "draft-route-test"
    assert (
        completed_body["outbound_messages"][0]["metadata"]["status"]
        == "onboarding_verification_pending"
    )
    assert sessions["telegram:route-test-user"].state == "completed"

    print("TELEGRAM_COMM_PRODUCTION_ROUTE_CHECK_PASSED")


if __name__ == "__main__":
    main()
