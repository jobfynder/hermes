"""Proves adding the signature parser did not change existing Hermes email
parsing behavior (hotlist/job_description extraction, confidence scoring,
classification) and that the new structured_data["signature"] key is
additive to app/channels/service.py::process_channel_intake.
"""

from uuid import uuid4

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.email_parsing.parsers import classify_email_by_confidence, parse_hotlist_email, parse_requirement_email


HOTLIST_EMAIL = (
    "Name | Title | Skills | Experience | Location | Email\n"
    "John Doe | Java Developer | Java, Spring | 8 | Dallas, TX | john.doe@example.com\n"
)

JOB_DESCRIPTION_EMAIL = (
    "Job Title: Senior Java Developer\n"
    "Required Skills: Java, Spring, Microservices, AWS\n"
    "Location: Remote\n"
    "We need a senior Java developer with strong microservices experience "
    "for a long-term client engagement.\n"
)


def test_hotlist_parsing_unchanged():
    result = parse_hotlist_email(HOTLIST_EMAIL)

    assert result["document_kind"] == "hotlist"
    assert result["record_count"] == 1
    assert result["records"][0]["candidate_name"] == "John Doe"
    assert result["parser"]["uses_llm"] is False


def test_requirement_parsing_unchanged():
    result = parse_requirement_email(JOB_DESCRIPTION_EMAIL)

    assert result["document_kind"] == "job_description"
    assert result["record_count"] == 1
    assert result["records"][0]["job_title"] == "Senior Java Developer"


def test_classification_unchanged():
    classification = classify_email_by_confidence(HOTLIST_EMAIL)

    assert classification is not None
    assert classification["document_kind"] == "hotlist"


def test_process_channel_intake_hotlist_still_produces_email_parsing_and_now_also_signature():
    request = ChannelIntakeRequest(
        channel="email",
        # Idempotency keys are persisted to a runtime JSONL log outside test
        # isolation (app/runtime/intake_log.py) -- a fixed id would be
        # flagged "duplicate" on any run after the first, so each test run
        # needs its own.
        source_message_id=f"regression-hotlist-{uuid4()}",
        sender=ChannelSender(email="recruiter@vendor.com"),
        content_type="text",
        text=(
            HOTLIST_EMAIL
            + "\n\nBest regards,\nRecruiter Name\nrecruiter@vendor.com\n"
        ),
        metadata={"intended_document_kind": "hotlist"},
    )

    response = process_channel_intake(request)

    assert response.intake_status == "parsed"
    assert response.document_kind == "hotlist"

    structured_data = response.understanding_result["structured_data"]
    assert "email_parsing" in structured_data
    assert structured_data["email_parsing"]["document_kind"] == "hotlist"

    # Additive: the new key exists alongside the untouched email_parsing key.
    assert "signature" in structured_data
    assert structured_data["signature"]["detected"] is True
    assert structured_data["signature"]["contact"]["email"]["value"] == "recruiter@vendor.com"


def test_process_channel_intake_non_email_channel_has_no_signature_key():
    request = ChannelIntakeRequest(
        channel="telegram",
        source_message_id=f"regression-telegram-{uuid4()}",
        content_type="text",
        text="Just a quick message, no signature parsing applies here.",
    )

    response = process_channel_intake(request)

    structured_data = response.understanding_result["structured_data"]
    assert "signature" not in structured_data
