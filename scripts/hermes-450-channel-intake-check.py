from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    health = client.get("/channels/health")
    assert_ok(health.status_code == 200, "channels health should return 200")
    assert_ok(health.json()["module"] == "HERMES-450", "health should identify HERMES-450")

    supported = client.get("/channels/supported")
    assert_ok(supported.status_code == 200, "supported channels should return 200")
    channels = supported.json()["channels"]
    for name in [
        "generic_api",
        "telegram",
        "email",
        "whatsapp",
        "slack",
        "teams",
        "google_chat",
    ]:
        assert_ok(name in channels, f"{name} should be registered")

    payload = {
        "channel": "generic_api",
        "source_message_id": "hermes-450-check-001",
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

    intake = client.post("/channels/intake", json=payload)
    assert_ok(intake.status_code == 200, f"intake should return 200: {intake.text}")
    data = intake.json()
    assert_ok(data["intake_status"] == "parsed", "intake should parse")
    assert_ok(data["document_kind"] == "job_description", "document kind should be job_description")
    assert_ok(data["draft_object_type"] == "draft_job_requirement", "draft object should be job requirement")
    assert_ok("Java" in data["normalized_skills"] or data["normalized_skills"], "normalized skills should exist")
    assert_ok(data["duplicate_key"] == "generic_api:hermes-450-check-001", "duplicate key should be stable")

    duplicate = client.post("/channels/intake", json=payload)
    assert_ok(duplicate.status_code == 200, "duplicate should return 200")
    duplicate_data = duplicate.json()
    assert_ok(duplicate_data["intake_status"] == "duplicate", "duplicate should be detected")
    assert_ok("duplicate_message" in duplicate_data["errors"], "duplicate error should be present")

    telegram_payload = {
        "update_id": 450001,
        "message": {
            "message_id": 77,
            "from": {
                "id": 12345,
                "first_name": "Pavan",
                "last_name": "Kumar",
                "username": "pavan",
            },
            "chat": {
                "id": 999,
                "type": "private",
            },
            "text": "Required skills: Python developer with FastAPI and PostgreSQL. Location Dallas.",
        },
    }

    telegram = client.post("/channels/telegram/webhook", json=telegram_payload)
    assert_ok(telegram.status_code == 200, f"telegram webhook should return 200: {telegram.text}")
    telegram_data = telegram.json()
    assert_ok(telegram_data["channel"] == "telegram", "telegram channel should be set")
    assert_ok(telegram_data["intake_status"] == "parsed", "telegram intake should parse")

    print("HERMES-450 channel intake verification passed")


if __name__ == "__main__":
    main()
