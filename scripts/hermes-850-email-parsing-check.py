from app.email_parsing.parsers import (
    parse_hotlist_email,
    parse_requirement_email,
)
from app.email_parsing.routing import classify_recipient_mailbox


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    require(
        classify_recipient_mailbox(
            ["hotlists@jobfynder.com"]
        ) == "hotlist",
        "Hotlist mailbox routing failed",
    )

    require(
        classify_recipient_mailbox(
            [{"email": "requirements@jobfynder.com"}]
        ) == "job_description",
        "Requirements mailbox routing failed",
    )

    hotlist_text = """
Name | Title | Skills | Experience | Location | Visa | Availability | Rate
John Smith | Java Developer | Java, AWS, Spring Boot | 8 years | Dallas, TX | H1B | Immediate | $75/hr
Mary Jones | Python Developer | Python, FastAPI, PostgreSQL | 6 years | Austin, TX | Green Card | 2 Weeks | $70/hr
"""

    hotlist_result = parse_hotlist_email(hotlist_text)

    require(
        hotlist_result["record_count"] == 2,
        "Expected two hotlist consultant records",
    )

    require(
        hotlist_result["parser"]["uses_llm"] is False,
        "Hotlist parser must not use an LLM",
    )

    require(
        hotlist_result["records"][0]["candidate_name"] == "John Smith",
        "First candidate name was not parsed",
    )

    requirement_text = """
Job Title: Senior Python Developer
Location: Dallas, TX
Required Skills: Python, FastAPI, PostgreSQL, AWS
Preferred Skills: Docker, Kubernetes
Experience: 7 years
Employment Type: Contract
Rate: $80/hr
Work Authorization: USC or Green Card

Need a senior Python developer for a long-term project.
"""

    requirement_result = parse_requirement_email(
        requirement_text
    )

    require(
        requirement_result["record_count"] == 1,
        "Expected one requirement record",
    )

    require(
        requirement_result["parser"]["uses_llm"] is False,
        "Requirement parser must not use an LLM",
    )

    require(
        requirement_result["records"][0]["job_title"]
        == "Senior Python Developer",
        "Job title was not parsed",
    )

    print("PASS: mailbox routing")
    print("PASS: two hotlist rows parsed")
    print("PASS: one requirement parsed")
    print("PASS: deterministic parser uses_llm=false")
    print("PASS: HERMES-850 email parsing foundation")


if __name__ == "__main__":
    main()
