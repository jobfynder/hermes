from uuid import uuid4

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.email.service import normalize_email_payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def hotlist_check() -> str:
    message_id = f"hermes-850-hotlist-{uuid4()}"

    payload = {
        "message_id": message_id,
        "from": {
            "name": "Bench Sales Recruiter",
            "email": "bsr@example.com",
        },
        "to": [
            {
                "name": "Jobfynder Hotlists",
                "email": "hotlists@jobfynder.com",
            }
        ],
        "subject": "Available Consultants Hotlist",
        "text": """
Name | Title | Skills | Experience | Location | Visa | Availability | Rate
John Smith | Java Developer | Java, AWS, Spring Boot | 8 years | Dallas, TX | H1B | Immediate | $75/hr
Mary Jones | Python Developer | Python, FastAPI, PostgreSQL | 6 years | Austin, TX | Green Card | 2 Weeks | $70/hr
""",
        "attachments": [],
        "provider": "integration_test",
    }

    normalized = normalize_email_payload(payload)

    require(
        normalized["metadata"]["intended_document_kind"] == "hotlist",
        "Hotlist recipient routing failed",
    )

    request = ChannelIntakeRequest(**normalized)
    result = process_channel_intake(request)

    require(
        result.intake_status == "parsed",
        f"Hotlist intake status was {result.intake_status}",
    )
    require(
        result.document_kind == "hotlist",
        f"Hotlist document kind was {result.document_kind}",
    )
    require(
        result.draft_object_type == "draft_hotlist",
        f"Unexpected hotlist draft type: {result.draft_object_type}",
    )

    structured = result.understanding_result.get(
        "structured_data",
        {},
    )
    email_parsing = structured.get("email_parsing", {})

    require(
        email_parsing.get("record_count") == 2,
        "Expected two consultant records",
    )
    require(
        email_parsing.get("parser", {}).get("uses_llm") is False,
        "Hotlist workflow must not use an LLM",
    )
    require(
        result.requires_review is False,
        "Complete hotlist should create a normal draft",
    )
    require(
        bool(result.understanding_result.get("draft_id")),
        "Hotlist draft ID was not created",
    )

    duplicate = process_channel_intake(request)

    require(
        duplicate.intake_status == "duplicate",
        "Duplicate hotlist email was not blocked",
    )
    require(
        "duplicate_message" in duplicate.errors,
        "Duplicate error was not returned",
    )

    print("PASS: hotlist mailbox routing")
    print("PASS: hotlist deterministic parsing")
    print("PASS: two consultant records")
    print("PASS: hotlist draft creation")
    print("PASS: duplicate email protection")

    return result.understanding_result["draft_id"]


def requirement_check() -> str:
    message_id = f"hermes-850-requirement-{uuid4()}"

    payload = {
        "message_id": message_id,
        "from": {
            "name": "Technical Recruiter",
            "email": "recruiter@example.com",
        },
        "to": "requirements@jobfynder.com",
        "subject": "Senior Python Developer Requirement",
        "text": """
Job Title: Senior Python Developer
Location: Dallas, TX
Required Skills: Python, FastAPI, PostgreSQL, AWS
Preferred Skills: Docker, Kubernetes
Experience: 7 years
Employment Type: Contract
Rate: $80/hr
Work Authorization: USC or Green Card

Need a senior Python developer for a long-term project.
""",
        "attachments": [],
        "provider": "integration_test",
    }

    normalized = normalize_email_payload(payload)

    require(
        normalized["metadata"]["intended_document_kind"]
        == "job_description",
        "Requirement recipient routing failed",
    )

    request = ChannelIntakeRequest(**normalized)
    result = process_channel_intake(request)

    require(
        result.intake_status == "parsed",
        f"Requirement intake status was {result.intake_status}",
    )
    require(
        result.document_kind == "job_description",
        f"Requirement document kind was {result.document_kind}",
    )
    require(
        result.draft_object_type == "draft_job_requirement",
        f"Unexpected requirement draft type: {result.draft_object_type}",
    )

    structured = result.understanding_result.get(
        "structured_data",
        {},
    )
    email_parsing = structured.get("email_parsing", {})
    records = email_parsing.get("records", [])

    require(
        email_parsing.get("record_count") == 1,
        "Expected one requirement record",
    )
    require(
        email_parsing.get("parser", {}).get("uses_llm") is False,
        "Requirement workflow must not use an LLM",
    )
    require(
        records[0].get("job_title") == "Senior Python Developer",
        "Requirement job title was not parsed",
    )
    require(
        bool(result.understanding_result.get("draft_id")),
        "Requirement draft ID was not created",
    )

    print("PASS: requirement mailbox routing")
    print("PASS: requirement deterministic parsing")
    print("PASS: requirement draft creation")
    print("PASS: requirement job title extraction")

    return result.understanding_result["draft_id"]


def main() -> None:
    hotlist_draft_id = hotlist_check()
    requirement_draft_id = requirement_check()

    print(f"hotlist_draft_id={hotlist_draft_id}")
    print(f"requirement_draft_id={requirement_draft_id}")
    print("PASS: HERMES-850 full email-to-draft integration")


if __name__ == "__main__":
    main()
