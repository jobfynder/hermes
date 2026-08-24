from app.email_parsing.parsers import (
    classify_email_by_confidence,
    parse_hotlist_email,
    parse_requirement_email,
)
from app.email_parsing.routing import classify_recipient_mailbox


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_mailbox_routing() -> None:
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

    require(
        classify_recipient_mailbox(
            ["Hotlists <hotlists@jobfynder.com>"]
        ) == "hotlist",
        "Named hotlist address routing failed",
    )

    require(
        classify_recipient_mailbox(
            ["hotlists@example.com"]
        ) == "unknown",
        "Foreign-domain hotlist alias must not route",
    )

    require(
        classify_recipient_mailbox(
            ["jobs@example.com"]
        ) == "unknown",
        "Foreign-domain jobs alias must not route",
    )

    require(
        classify_recipient_mailbox(
            [
                "hotlists@jobfynder.com",
                "requirements@jobfynder.com",
            ]
        ) == "unknown",
        "Ambiguous mailbox routing must require review",
    )


def test_hotlist_parser() -> None:
    hotlist_text = """
Name | Title | Skills | Experience | Location | Visa | Availability | Rate
John Smith | Java Developer | Java, AWS, Spring Boot | 8 years | Dallas, TX | H1B | Immediate | $75/hr
Mary Jones | Python Developer | Python, FastAPI, PostgreSQL | 6 years | Austin, TX | Green Card | 2 Weeks | $70/hr
"""

    result = parse_hotlist_email(hotlist_text)

    require(
        result["record_count"] == 2,
        "Expected two consultant records",
    )
    require(
        result["parser"]["uses_llm"] is False,
        "Hotlist parser must not use an LLM",
    )
    require(
        result["records"][0]["candidate_name"]
        == "John Smith",
        "First candidate name was not parsed",
    )
    require(
        result["requires_review"] is False,
        "Complete hotlist should not require review",
    )

    empty_result = parse_hotlist_email("")

    require(
        empty_result["record_count"] == 0,
        "Empty hotlist must not create a blank record",
    )
    require(
        empty_result["requires_review"] is True,
        "Empty hotlist must require review",
    )


def test_requirement_parser() -> None:
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

    result = parse_requirement_email(requirement_text)

    require(
        result["record_count"] == 1,
        "Expected one requirement record",
    )
    require(
        result["parser"]["uses_llm"] is False,
        "Requirement parser must not use an LLM",
    )
    require(
        result["records"][0]["job_title"]
        == "Senior Python Developer",
        "Job title was not parsed",
    )
    require(
        result["requires_review"] is False,
        "Complete requirement should not require review",
    )

    title_only = parse_requirement_email(
        "Job Title: Senior Python Developer"
    )

    require(
        title_only["record_count"] == 1,
        "Title-only requirement should remain visible",
    )
    require(
        title_only["requires_review"] is True,
        "Title-only requirement must require review",
    )
    require(
        title_only["confidence"] < 0.70,
        "Title-only requirement confidence must be low",
    )
    require(
        "required_skills_not_identified"
        in title_only["records"][0]["warnings"],
        "Missing skills warning was not generated",
    )

    empty_result = parse_requirement_email("")

    require(
        empty_result["record_count"] == 0,
        "Empty requirement must not create a blank record",
    )
    require(
        empty_result["requires_review"] is True,
        "Empty requirement must require review",
    )


def test_confidence_based_classification() -> None:
    # Same fixtures as test_hotlist_parser/test_requirement_parser -- a
    # single shared mailbox (see .env.example's HERMES_MS_GRAPH_MAILBOXES
    # note) has no recipient-address signal, so this is what actually
    # resolves hotlist vs. job_description for real inbound mail.
    hotlist_text = """
Name | Title | Skills | Experience | Location | Visa | Availability | Rate
John Smith | Java Developer | Java, AWS, Spring Boot | 8 years | Dallas, TX | H1B | Immediate | $75/hr
Mary Jones | Python Developer | Python, FastAPI, PostgreSQL | 6 years | Austin, TX | Green Card | 2 Weeks | $70/hr
"""
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

    hotlist_classification = classify_email_by_confidence(hotlist_text)
    require(
        hotlist_classification is not None
        and hotlist_classification["document_kind"] == "hotlist",
        "A clear hotlist email must classify as hotlist by confidence",
    )

    requirement_classification = classify_email_by_confidence(requirement_text)
    require(
        requirement_classification is not None
        and requirement_classification["document_kind"] == "job_description",
        "A clear requirement email must classify as job_description by confidence",
    )

    require(
        classify_email_by_confidence("") is None,
        "Empty text must return None (nothing to guess from), not a fabricated classification",
    )
    require(
        classify_email_by_confidence("Hi, just checking in on last week's call.") is None,
        "Ordinary correspondence with no hotlist/requirement structure must return None",
    )


def main() -> None:
    test_mailbox_routing()
    test_hotlist_parser()
    test_requirement_parser()
    test_confidence_based_classification()

    print("PASS: exact mailbox routing")
    print("PASS: foreign-domain aliases rejected")
    print("PASS: ambiguous mailbox rejected")
    print("PASS: two hotlist rows parsed")
    print("PASS: empty hotlist creates no record")
    print("PASS: complete requirement parsed")
    print("PASS: title-only requirement requires review")
    print("PASS: empty requirement creates no record")
    print("PASS: deterministic parser uses_llm=false")
    print("PASS: confidence-based hotlist/requirement classification (shared mailbox)")
    print("PASS: HERMES-850 parser guardrails")


if __name__ == "__main__":
    main()
