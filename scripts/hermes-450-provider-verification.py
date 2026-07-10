import hashlib
import hmac
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
RUN_ID = str(int(time.time()))


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


import os

COMM_SECRET = os.getenv("HERMES_COMM_SHARED_SECRET")
assert COMM_SECRET, "HERMES_COMM_SHARED_SECRET missing"
TELEGRAM_SECRET = os.getenv("HERMES_TELEGRAM_WEBHOOK_SECRET", "")


def signed_headers(body: bytes, timestamp: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))

    signature = hmac.new(
        COMM_SECRET.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    return {
        "Content-Type": "application/json",
        "X-Jobfynder-Timestamp": timestamp,
        "X-Jobfynder-Signature": signature,
    }


def post_signed(path: str, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return client.post(
        path,
        content=body,
        headers=signed_headers(body),
    )


def test_health() -> None:
    response = client.get("/health")
    assert_ok(response.status_code == 200, "health endpoint failed")
    assert_ok(response.json()["status"] == "healthy", "Hermes is not healthy")


def test_provider_registry() -> None:
    response = client.get("/providers/status")
    assert_ok(response.status_code == 200, "provider registry failed")

    data = response.json()

    assert_ok("telegram" in data["configured"], "Telegram not configured")
    assert_ok("email" in data["contracts"], "Email contract missing")
    assert_ok("whatsapp" in data["contracts"], "WhatsApp contract missing")
    assert_ok("slack" in data["contracts"], "Slack contract missing")
    assert_ok("teams" in data["contracts"], "Teams contract missing")
    assert_ok("google_chat" in data["contracts"], "Google Chat contract missing")


def test_comm_signature_security() -> None:
    payload = {
        "message": {
            "id": f"wa-security-{RUN_ID}",
            "from": "+15550000001",
            "text": {
                "body": "Job description: Python developer required with AWS."
            },
        },
        "provider": "verification",
    }

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    unsigned = client.post(
        "/providers/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert_ok(unsigned.status_code == 403, "unsigned COMM request was accepted")

    bad = client.post(
        "/providers/whatsapp/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Jobfynder-Timestamp": str(int(time.time())),
            "X-Jobfynder-Signature": "invalid",
        },
    )
    assert_ok(bad.status_code == 403, "bad COMM signature was accepted")

    expired_timestamp = str(int(time.time()) - 600)
    expired = client.post(
        "/providers/whatsapp/webhook",
        content=body,
        headers=signed_headers(body, expired_timestamp),
    )
    assert_ok(expired.status_code == 403, "expired COMM request was accepted")

    valid = client.post(
        "/providers/whatsapp/webhook",
        content=body,
        headers=signed_headers(body),
    )
    assert_ok(valid.status_code == 200, "valid COMM request was rejected")


def test_email_contract() -> None:
    response = post_signed(
        "/providers/email/webhook",
        {
            "message_id": f"email-{RUN_ID}",
            "from": {
                "email": "recruiter@example.com",
                "name": "Provider Verification",
            },
            "subject": "Java Developer Requirement",
            "text": (
                "Job description: Java developer required with AWS "
                "and PostgreSQL."
            ),
            "provider": "verification",
        },
    )

    assert_ok(response.status_code == 200, "Email contract failed")

    data = response.json()
    assert_ok(data["channel"] == "email", "Email channel mismatch")
    assert_ok(
        data["draft_object_type"] == "draft_job_requirement",
        "Email draft type mismatch",
    )


def test_whatsapp_contract() -> None:
    response = post_signed(
        "/providers/whatsapp/webhook",
        {
            "message": {
                "id": f"wa-{RUN_ID}",
                "from": "+15550000002",
                "text": {
                    "body": (
                        "Job description: Python developer required "
                        "with FastAPI and AWS."
                    )
                },
            },
            "provider": "verification",
        },
    )

    assert_ok(response.status_code == 200, "WhatsApp contract failed")
    assert_ok(
        response.json()["draft_object_type"] == "draft_job_requirement",
        "WhatsApp draft type mismatch",
    )


def test_slack_contract() -> None:
    response = post_signed(
        "/providers/slack/webhook",
        {
            "team_id": "T001",
            "event_id": f"slack-event-{RUN_ID}",
            "event": {
                "type": "message",
                "client_msg_id": f"slack-{RUN_ID}",
                "user": "U001",
                "channel": "C001",
                "text": (
                    "Hotlist: Java consultant with AWS and Kubernetes."
                ),
            },
        },
    )

    assert_ok(response.status_code == 200, "Slack contract failed")
    assert_ok(
        response.json()["draft_object_type"] == "draft_hotlist",
        "Slack draft type mismatch",
    )


def test_teams_contract() -> None:
    response = post_signed(
        "/providers/teams/webhook",
        {
            "id": f"teams-{RUN_ID}",
            "from": {
                "id": "teams-user-001",
                "name": "Teams Verification",
            },
            "conversation": {
                "id": "teams-conversation-001",
            },
            "text": (
                "Job description: Java developer required "
                "with Azure and Docker."
            ),
            "channelId": "msteams",
        },
    )

    assert_ok(response.status_code == 200, "Teams contract failed")
    assert_ok(
        response.json()["draft_object_type"] == "draft_job_requirement",
        "Teams draft type mismatch",
    )


def test_google_chat_contract() -> None:
    response = post_signed(
        "/providers/google-chat/webhook",
        {
            "message": {
                "name": f"spaces/test/messages/google-{RUN_ID}",
                "text": (
                    "Job description: DevOps Engineer required "
                    "with AWS, Docker and Kubernetes."
                ),
                "sender": {
                    "name": "users/google-verification",
                    "displayName": "Google Verification",
                },
                "space": {
                    "name": "spaces/test",
                    "type": "DM",
                },
            },
        },
    )

    assert_ok(response.status_code == 200, "Google Chat contract failed")

    data = response.json()
    assert_ok(
        data["draft_object_type"] == "draft_job_requirement",
        "Google Chat draft type mismatch",
    )
    assert_ok(
        "DevOps Engineer" in data["normalized_job_titles"],
        "Google Chat job-title normalization failed",
    )


def telegram_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET,
    }


def test_telegram_security_and_workflow() -> None:
    missing_secret = client.post(
        "/channels/telegram/webhook",
        json={
            "update_id": 800001,
            "message": {
                "message_id": 800001,
                "text": "/start",
                "chat": {"id": 800001, "type": "private"},
                "from": {"id": 800001, "first_name": "Verification"},
            },
        },
    )
    assert_ok(
        missing_secret.status_code == 403,
        "Telegram accepted missing webhook secret",
    )

    user_id = int(RUN_ID[-7:]) + 900000

    start = client.post(
        "/channels/telegram/webhook",
        headers=telegram_headers(),
        json={
            "update_id": user_id,
            "message": {
                "message_id": user_id,
                "text": "/start",
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Verification"},
            },
        },
    )
    assert_ok(start.status_code == 200, "Telegram /start failed")
    assert_ok(
        start.json()["understanding_result"]["should_parse"] is False,
        "Telegram /start entered parser",
    )

    action = client.post(
        "/channels/telegram/webhook",
        headers=telegram_headers(),
        json={
            "update_id": user_id + 1,
            "message": {
                "message_id": user_id + 1,
                "text": "BSR: Post Hotlist",
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Verification"},
            },
        },
    )
    assert_ok(action.status_code == 200, "Telegram action selection failed")
    assert_ok(
        action.json()["understanding_result"]["state"]
        == "waiting_for_hotlist",
        "Telegram session did not enter waiting_for_hotlist",
    )

    business_input = client.post(
        "/channels/telegram/webhook",
        headers=telegram_headers(),
        json={
            "update_id": user_id + 2,
            "message": {
                "message_id": user_id + 2,
                "text": (
                    "Hotlist: Java consultant with AWS and Kubernetes "
                    "available immediately."
                ),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Verification"},
            },
        },
    )

    assert_ok(
        business_input.status_code == 200,
        "Telegram business input failed",
    )
    assert_ok(
        business_input.json()["draft_object_type"] == "draft_hotlist",
        "Telegram hotlist draft was not created",
    )


def test_telegram_onboarding() -> None:
    user_id = int(RUN_ID[-7:]) + 950000

    start = client.post(
        "/channels/telegram/webhook",
        headers=telegram_headers(),
        json={
            "update_id": user_id,
            "message": {
                "message_id": user_id,
                "text": "Onboarding: Start",
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Onboarding"},
            },
        },
    )
    assert_ok(start.status_code == 200, "Telegram onboarding start failed")

    details = client.post(
        "/channels/telegram/webhook",
        headers=telegram_headers(),
        json={
            "update_id": user_id + 1,
            "message": {
                "message_id": user_id + 1,
                "text": (
                    "Role: BSR\n"
                    "Name: Verification User\n"
                    "Company: Jobfynder\n"
                    "Email: verification@jobfynder.com\n"
                    "LinkedIn: https://www.linkedin.com/in/example\n"
                    "Location: India\n"
                    "Focus: US IT Staffing Bench Sales"
                ),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Onboarding"},
            },
        },
    )

    assert_ok(details.status_code == 200, "Telegram onboarding details failed")

    data = details.json()
    assert_ok(
        data["draft_object_type"] == "draft_bench_sales_profile",
        "Onboarding draft type mismatch",
    )
    assert_ok(data["requires_review"] is True, "Onboarding review flag missing")


def main() -> None:
    test_health()
    test_provider_registry()
    test_comm_signature_security()
    test_email_contract()
    test_whatsapp_contract()
    test_slack_contract()
    test_teams_contract()
    test_google_chat_contract()
    test_telegram_security_and_workflow()
    test_telegram_onboarding()

    print("HERMES-450 combined provider verification passed")


if __name__ == "__main__":
    main()
