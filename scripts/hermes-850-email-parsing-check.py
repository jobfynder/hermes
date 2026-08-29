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
            [{"email": "jobs@jobfynder.com"}]
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
                "jobs@jobfynder.com",
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


def test_forwarded_requirement_with_end_client() -> None:
    # Regression fixture for the HERMES-850 "jobs@ mail isn't parsing
    # right" incident: a real vendor-forwarded posting where the actual
    # job title/JD content sits several paragraphs past a forwarded-
    # message header block, the end client is only named inline (not
    # under a "Job Title:" label the deterministic parser already knew
    # about), and the source HTML used <br>/<p> for line breaks.
    text = (
        "Subject: FW: AWS Connect Solutions Engineer with IVR Exp : Houston, TX (onsite) - Oncor\n"
        "\n"
        "From: harry@itecsus.com <harry@itecsus.com>\n"
        "Sent: Saturday, August 29, 2026 6:38 AM\n"
        "To: Jobs Nvoids <jobs@nvoids.com>\n"
        "Subject: AWS Connect Solutions Engineer with IVR Exp : Houston, TX (onsite) - Oncor\n"
        "\n"
        "You received this email from harry@itecsus.com via https://jobs.nvoids.com\n"
        "\n"
        "AWS Connect Solutions Engineer\n"
        "Location: Dallas TX\n"
        "End client: Oncor\n"
        "( Need Only Independent Visa)\n"
        "Required skills: Amazon Connect, AWS Lambda, TIBCO BusinessWorks\n"
        "\n"
        "Nice to have skills:\n"
        "\n"
        "Experience with Amazon Lex and AWS certification is a plus.\n"
        "\n"
        "linkedin.com/in/harry-recruiter\n"
        "\n"
        "Keywords: artificial intelligence sthree database information technology\n"
        "View this job online here\n"
    )

    result = parse_requirement_email(text)
    record = result["records"][0]

    require(
        record["job_title"] == "AWS Connect Solutions Engineer",
        f"Expected the email subject to supply the job title when the body's own "
        f"labeled title comes late, got {record['job_title']!r}",
    )
    require(
        record["company"] == "Oncor",
        f"Expected 'End client: Oncor' to be extracted as company, got {record['company']!r}",
    )
    require(
        record["location"] == "Dallas TX",
        f"Location must not bleed into the following 'End client' line, got {record['location']!r}",
    )
    require(
        "From: harry@itecsus.com" not in record["job_description"],
        "The forwarded-message header block must be stripped from job_description",
    )
    require(
        "Keywords:" not in record["job_description"],
        "The trailing keyword-dump footer must be stripped from job_description",
    )
    require(
        "Oncor" in record["job_description"],
        "Cleaning job_description must not strip real posting content",
    )
    require(
        record["work_authorization"] == "Independent Visa",
        f"Expected staffing-industry 'Independent Visa' phrasing to be recognized, got {record['work_authorization']!r}",
    )
    require(
        record["linkedin_url"] == "https://linkedin.com/in/harry-recruiter",
        f"Expected a bare linkedin.com/in/... URL in the JD body to be extracted, got {record['linkedin_url']!r}",
    )
    require(
        "TIBCO BusinessWorks" in record["required_skills"] and "Amazon Connect" in record["required_skills"],
        f"Expected IT-staffing-domain taxonomy terms in required_skills, got {record['required_skills']}",
    )
    require(
        record["preferred_skills"] != [],
        "Expected the multi-word 'Nice to have skills:' label to still match and produce a non-empty section",
    )


def main() -> None:
    test_mailbox_routing()
    test_hotlist_parser()
    test_requirement_parser()
    test_confidence_based_classification()
    test_forwarded_requirement_with_end_client()

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
    print("PASS: company/work-authorization/LinkedIn/taxonomy-driven skills on a real forwarded posting")
    print("PASS: HERMES-850 parser guardrails")


if __name__ == "__main__":
    main()
