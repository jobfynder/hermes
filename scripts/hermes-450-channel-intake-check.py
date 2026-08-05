from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.sessions.service import (
    get_or_create_session,
    start_waiting_for_action,
)


client = TestClient(app)

RUN_ID = str(uuid4())


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_health() -> None:
    response = client.get("/channels/health")
    assert_ok(response.status_code == 200, "channels health should return 200")
    data = response.json()
    assert_ok(data["status"] == "ok", "health status should be ok")
    assert_ok(data["module"] == "HERMES-450", "health should identify HERMES-450")


def test_supported_channels() -> None:
    response = client.get("/channels/supported")
    assert_ok(response.status_code == 200, "supported channels should return 200")
    channels = response.json()["channels"]

    for name in [
        "generic_api",
        "telegram",
        "email",
        "whatsapp",
        "slack",
        "teams",
        "google_chat",
        "browser_extension",
        "web_upload",
    ]:
        assert_ok(name in channels, f"{name} should be registered")


def test_text_intake_and_duplicate() -> None:
    payload = {
        "channel": "generic_api",
        "source_message_id": f"hermes-450-check-text-{RUN_ID}",
        "sender": {
            "sender_id": "test-user",
            "sender_name": "Hermes Test",
        },
        "content_type": "text",
        "text": "Job description: Java developer required with AWS, Kubernetes, and Spring Boot. Location remote. Rate open.",
        "attachments": [],
        "metadata": {
            "test": True,
        },
    }

    response = client.post("/channels/intake", json=payload)
    assert_ok(response.status_code == 200, f"text intake should return 200: {response.text}")
    data = response.json()

    assert_ok(data["intake_status"] == "parsed", "text intake should parse")
    assert_ok(data["document_kind"] == "job_description", "document kind should be job_description")
    assert_ok(data["draft_object_type"] == "draft_job_requirement", "draft object should be job requirement")
    assert_ok("AWS" in data["normalized_skills"], "AWS should be normalized")
    assert_ok("Java" in data["normalized_skills"], "Java should be normalized")
    assert_ok(data["duplicate_key"] == f"generic_api:hermes-450-check-text-{RUN_ID}", "duplicate key should be stable")

    duplicate = client.post("/channels/intake", json=payload)
    assert_ok(duplicate.status_code == 200, "duplicate should return 200")
    duplicate_data = duplicate.json()
    assert_ok(duplicate_data["intake_status"] == "duplicate", "duplicate should be detected")
    assert_ok("duplicate_message" in duplicate_data["errors"], "duplicate error should be present")


def test_telegram_webhook_intake() -> None:
    telegram_user_id = str(
        int(RUN_ID.replace("-", "")[:10], 16)
    )
    telegram_chat_id = f"test-chat-{RUN_ID}"

    session = get_or_create_session(
        channel="telegram",
        external_user_id=telegram_user_id,
        chat_id=telegram_chat_id,
    )

    transition = start_waiting_for_action(
        session=session,
        role="recruiter",
        action="post_job_requirement",
    )

    assert_ok(
        transition.session.action == "post_job_requirement",
        "telegram recruiter workflow should be active",
    )
    assert_ok(
        transition.should_parse is False,
        "telegram action selection should wait for input",
    )

    payload = {
        "update_id": int(
            RUN_ID.replace("-", "")[:8],
            16,
        ) % 100000000,
        "message": {
            "message_id": int(
                RUN_ID.replace("-", "")[8:16],
                16,
            ) % 100000000,
            "from": {
                "id": int(telegram_user_id),
                "first_name": "Pavan",
                "last_name": "Kumar",
                "username": "pavan",
            },
            "chat": {
                "id": telegram_chat_id,
                "type": "private",
            },
            "text": (
                "Job Title: Python Developer\n"
                "Required Skills: Python, FastAPI, PostgreSQL\n"
                "Location: Dallas, TX\n"
                "Employment Type: Contract"
            ),
        },
    }

    response = client.post(
        "/channels/telegram/webhook",
        json=payload,
    )

    assert_ok(
        response.status_code == 200,
        f"telegram webhook should return 200: {response.text}",
    )

    data = response.json()

    assert_ok(
        data["channel"] == "telegram",
        "telegram channel should be set",
    )
    assert_ok(
        data["intake_status"] == "parsed",
        f"telegram intake should parse: {data}",
    )
    assert_ok(
        data["document_kind"] == "job_description",
        "telegram workflow should create a job requirement",
    )
    assert_ok(
        data["draft_object_type"] == "draft_job_requirement",
        "telegram workflow should create a requirement draft",
    )
    assert_ok(
        "Python" in data["normalized_skills"],
        "Python should be normalized",
    )


def test_file_intake() -> None:
    content = (
        "Job description: Python developer required with FastAPI, PostgreSQL, "
        "AWS and Docker. Location remote."
    ).encode("utf-8")

    response = client.post(
        "/channels/intake/file",
        data={
            "channel": "generic_api",
            "source_message_id": f"hermes-450-check-file-{RUN_ID}",
            "document_kind": "job_description",
        },
        files={
            "file": ("hermes-test-jd.txt", content, "text/plain"),
        },
    )

    assert_ok(response.status_code == 200, f"file intake should return 200: {response.text}")
    data = response.json()

    assert_ok(data["result_version"] == "hermes_file_intake_result_v1", "file result version should match")
    assert_ok(data["channel"] == "generic_api", "file channel should be returned")
    assert_ok(data["source_message_id"] == f"hermes-450-check-file-{RUN_ID}", "file source id should be returned")
    assert_ok(data["intake_status"] == "parsed", "file intake should parse")
    assert_ok(data["document_kind"] == "job_description", "file document kind should match")
    assert_ok(data["draft_object_type"] == "draft_job_requirement", "file draft object should be job requirement")
    assert_ok(data["attachment"]["status"] == "stored", "attachment should be stored")
    assert_ok(data["attachment"]["checksum_sha256"], "attachment checksum should exist")
    assert_ok(Path(data["attachment"]["storage_ref"]).name.endswith(".txt"), "storage ref should preserve extension")
    assert_ok("Python" in data["normalized_skills"], "Python should be normalized from file")
    assert_ok("FastAPI" in data["normalized_skills"], "FastAPI should be normalized from file")
    assert_ok(data["confidence"] >= 0.7, "file confidence should be acceptable")



def test_onboarding_intake_pipeline() -> None:
    session_response = client.post(
        "/onboarding/session",
        json={
            "user_id": "test-user-027",
            "role": "bench_sales",
            "channel": "telegram",
            "channel_user_id": "telegram-123",
            "sender_name": "Pavan Kumar",
            "metadata": {
                "test": True,
            },
        },
    )

    assert_ok(
        session_response.status_code == 200,
        f"onboarding session should return 200: {session_response.text}",
    )
    session = session_response.json()
    session_id = session["session_id"]

    assert_ok(session["role"] == "bench_sales", "session role should be bench_sales")
    assert_ok(session["status"] == "role_selected", "session should be role_selected")

    draft_response = client.post(
        "/onboarding/profile/draft",
        json={
            "session_id": session_id,
            "role": "bench_sales",
            "source": "manual_text",
            "profile_text": (
                "Pavan Kumar\n"
                "Bench Sales Recruiter focused on US IT Staffing, vendor management, "
                "Java consultants, Python consultants, AWS, Docker, Kubernetes, "
                "remote submissions and recruiter relationships."
            ),
            "metadata": {
                "test": True,
            },
        },
    )

    assert_ok(
        draft_response.status_code == 200,
        f"onboarding profile draft should return 200: {draft_response.text}",
    )
    draft = draft_response.json()

    assert_ok(draft["result_version"] == "hermes_onboarding_profile_draft_v1", "draft version should match")
    assert_ok(draft["profile_status"] == "draft", "profile should be draft")
    assert_ok(draft["role"] == "bench_sales", "draft role should be bench_sales")
    assert_ok(draft["headline"] == "Bench Sales Recruiter", "headline should be inferred")
    assert_ok("Bench Sales" in draft["specializations"], "Bench Sales specialization should exist")
    assert_ok("US IT Staffing" in draft["specializations"], "US IT Staffing specialization should exist")
    assert_ok(draft["requires_review"] is True, "draft should require review")

    read_draft_response = client.get(f"/onboarding/profile/draft/{session_id}")
    assert_ok(read_draft_response.status_code == 200, "read draft should return 200")
    assert_ok(read_draft_response.json()["session_id"] == session_id, "read draft should match session")

    publish_response = client.post(f"/onboarding/profile/publish/{session_id}")
    assert_ok(publish_response.status_code == 200, "publish should return 200")
    publish = publish_response.json()

    assert_ok(publish["status"] == "published", "profile publish should be successful")
    assert_ok(publish["profile_status"] == "published", "profile status should be published")

def main() -> None:
    test_health()
    test_supported_channels()
    test_text_intake_and_duplicate()
    test_telegram_webhook_intake()
    test_file_intake()

    print("HERMES-450 combined channel and file intake verification passed")


if __name__ == "__main__":
    main()
