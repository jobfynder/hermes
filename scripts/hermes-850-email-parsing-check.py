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
Company: Acme Corp
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
        result["records"][0]["company"] == "Acme Corp",
        "Company was not parsed",
    )
    require(
        result["requires_review"] is False,
        "Complete requirement (including company) should not require review",
    )

    # A posting with a clear title and a real skills section but no company
    # line used to score the same 0.92 as a fully complete one -- silently
    # skipping the LLM fallback (app/email_parsing/llm_fallback.py) on
    # exactly the emails it exists for. Confirmed in production: 90% of
    # real postings have no explicit "Company:" label. This must now stay
    # below FALLBACK_CONFIDENCE_THRESHOLD (0.70) so the fallback engages.
    missing_company = parse_requirement_email(
        """
Job Title: Senior Python Developer
Location: Dallas, TX
Required Skills: Python, FastAPI, PostgreSQL, AWS
Experience: 7 years

Need a senior Python developer for a long-term project.
"""
    )

    require(
        missing_company["records"][0]["company"] is None,
        "Fixture must genuinely have no company for this case to be meaningful",
    )
    require(
        missing_company["confidence"] < 0.70,
        "Title+skills without company must fall below the fallback threshold",
    )
    require(
        missing_company["requires_review"] is True,
        "Requirement missing only company must require review",
    )
    require(
        "company_missing" in missing_company["records"][0]["warnings"],
        "Missing company warning was not generated",
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
Company: Acme Corp
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


def test_nvoids_java_posting_regression() -> None:
    # Real production email (jobs.nvoids.com relay) reported by the user as
    # inaccurately parsed: company came back as the entire "MUST HAVE"
    # skills paragraph (a COMPANY_SUFFIX_RE false hit on "MESSAGING
    # SERVICES"), location came back as "Omaha, NE- 100" (the "100%
    # onsite" percentage bleeding into the value), and skills included a
    # spurious ".NET" that never appears anywhere in the text (rapidfuzz
    # partial_ratio scoring a short needle against the whole email body).
    text = (
        "Subject: Java Developer onsite omaha ne no\n"
        "\n"
        "You received this email from jigyansh@paramountsoft.net via https://jobs.nvoids.com \n"
        "Please check the email id in the signature to reply to the correct email id.\n"
        "\n"
        "From:\n"
        "\n"
        "Jigi,\n"
        "\n"
        "Paramount software solutions\n"
        "\n"
        "jigyansh@paramountsoft.net\n"
        "\n"
        "Reply to: jigyansh@paramountsoft.net\n"
        "\n"
        "Position: Mid Level Java Full Stack Developer\n"
        "Location: Omaha, NE- 100% onsite\n"
        "Duration: 12+ months contract\n"
        "50+ positions no , or F1 \n"
        ", cpt we can try but i94 will be needed by client !!\n"
        "\n"
        "MUST HAVE:\n"
        "JAVA 8,21 , ANGULAR 8, 21 , SPRING BOOT, APACHE SPARK, MONGODB, MYSQL, REST APIS, "
        "MESSAGING SERVICES EXPERIENCE SUCH AS KAFKA, AWS SDK BASIC, AZURE SDK BASIC , oracle database \n"
        "DOCKER, IOT, ETL TOOLS, LINUX BASIC, DATA ANALYTICS (TABLEAU), AZURE IOT HUB AND AZURE EVENT HUB "
        "IS A PLUS AND INTEGRATION TESTING. ENTERPRISE JAVA 8. 21 must \n"
        "\n"
        "Keywords: information technology card Nebraska \n"
        "Java Developer onsite omaha ne no\n"
        "jigyansh@paramountsoft.net\n"
        "\n"
        "View this job online here \n"
        "\n"
        "Happy recruiting \n"
        "https://jobs.nvoids.com \n"
        "Free resume and job search portal"
    )

    result = parse_requirement_email(text)
    record = result["records"][0]

    require(
        record["location"] == "Omaha, NE",
        f"Expected the '100% onsite' qualifier to be trimmed from location, got {record['location']!r}",
    )
    require(
        ".NET" not in record["required_skills"],
        f"Expected no spurious fuzzy '.NET' match (never mentioned in the text), got {record['required_skills']}",
    )
    require(
        "You received this email from" not in record["job_description"],
        "The jobs.nvoids.com relay preamble must be stripped from job_description",
    )
    require(
        result["confidence"] < 0.70,
        "Missing company must keep this below the fallback threshold so the LLM fallback engages",
    )


def test_location_does_not_swallow_next_blank_label() -> None:
    # A recruiter template asking the reader to fill in several blank
    # fields ("Location:\nLinkedIn:\n...") used to have its empty
    # "Location:" swallow the next label's own name as if it were the
    # location value, because the regex's \s* between colon and value
    # could cross the newline. The real location line further down the
    # email must still be found.
    text = (
        "While replying back mention\n"
        "Location:\n"
        "LinkedIn:\n"
        "Years of experience with Workday Extend:\n"
        "\n"
        "Position:- Workday Extend Developer\n"
        "Location: San Jose, CA - HYBRID\n"
        "Required Skills: Workday Extend, PMD Scripting, Orchestrations\n"
    )

    result = parse_requirement_email(text)
    record = result["records"][0]

    require(
        record["location"] == "Hybrid - San Jose, CA",
        f"Expected the blank 'Location:' template field to be skipped in favor of the real one, got {record['location']!r}",
    )


def test_security_gateway_banner_is_stripped() -> None:
    # Corporate email-security gateways (Microsoft Defender, Proofpoint,
    # Mimecast) inject a banner ahead of any externally-sourced email --
    # which is *all* recruiter/vendor mail by definition, so this shows
    # up constantly in real inbound requirements. Left unstripped, this
    # was exactly the same class of bug as the jobs.nvoids.com preamble:
    # sitting right at the top, where a title/company guess looks first.
    text = (
        "[EXTERNAL]\n"
        "\n"
        "CAUTION: This email originated from outside the organization. "
        "Do not click links or open attachments unless you recognize the sender.\n"
        "\n"
        "Job Title: Senior Java Developer\n"
        "Company: Acme Staffing\n"
        "Location: Dallas, TX\n"
        "Required Skills: Java, Spring Boot, AWS\n\n"
        "Please share updated resumes for this role.\n"
    )

    result = parse_requirement_email(text)
    record = result["records"][0]

    require(
        record["job_title"] == "Senior Java Developer",
        f"Expected the banner to not interfere with job_title extraction, got {record['job_title']!r}",
    )
    require(
        "CAUTION" not in record["job_description"] and "[EXTERNAL]" not in record["job_description"],
        "The security-gateway banner must be stripped from job_description",
    )


def test_pipe_delimited_subject_still_yields_a_title() -> None:
    # Real production regression: "Senior SAP ERP Developer | Remote |"
    # never produced a title at all -- extract_probable_title's regex had
    # no terminator for "|", so the match failed the instant it hit the
    # pipe character with nothing else in the allowed character class.
    # Confirmed against three real Jobfynder subjects using this exact
    # "Title | Location |" / "Title || Location || Duration" shape.
    text = (
        "Subject: Senior SAP ERP Developer | Remote |\n\n"
        "We are looking for a Senior SAP ERP Developer with strong SAP "
        "ABAP and Fiori expertise.\n\n"
        "Required Skills: SAP ABAP, SAP Fiori\n"
    )

    result = parse_requirement_email(text)
    record = result["records"][0]

    require(
        record["job_title"] == "Senior SAP ERP Developer",
        f"Expected the pipe-delimited subject to still yield a title, got {record['job_title']!r}",
    )


def test_job_description_excludes_everything_from_the_signoff_onward() -> None:
    # Real production regression: a footer that never said "Keywords:"/
    # "unsubscribe" (the only two markers _strip_job_description_footer
    # checked for) was leaving a trailing "--" and the sender's contact
    # block inside job_description. Everything from the signoff itself
    # onward is never job content.
    text = (
        "Subject: Senior Agentic AI Engineer\n\n"
        "You received this email from recruiter@example.com via https://jobs.nvoids.com\n"
        "Please check the email id in the signature to reply to the correct email id.\n\n"
        "Role Senior Agentic AI Engineer\n\n"
        "JOB SUMMARY\n\n"
        "Strong hands-on experience designing Agentic AI solutions.\n\n"
        "--\n\n"
        "Keywords: artificial intelligence Texas\n"
        "recruiter@example.com\n\n"
        "Happy recruiting\n"
        "https://jobs.nvoids.com\n"
    )

    result = parse_requirement_email(text)
    job_description = result["records"][0]["job_description"]

    require("--" not in job_description, f"The signoff marker itself must not remain: {job_description!r}")
    require(
        "recruiter@example.com" not in job_description and "jobs.nvoids.com" not in job_description,
        f"Contact info/relay links from the footer must never leak into job_description: {job_description!r}",
    )
    require(
        job_description.strip().endswith("Agentic AI solutions."),
        f"The real content must still be there, just nothing after it: {job_description!r}",
    )


def test_numbered_multi_position_email_splits_into_separate_records() -> None:
    # Real production email (jobs.nvoids.com relay): one recruiter
    # posting three distinct positions as a numbered list rather than
    # repeating a "Job Title:" label per posting. Previously produced a
    # single garbled record: job_title=None, required_skills mixing junk
    # tokens like "https" pulled off the footer URL, and the entire
    # three-position block dumped into one job_description.
    text = """Subject: Requirement : Power Platform Developer : Sacramento, CA

You received this email from ravisharpedge70@gmail.com via https://jobs.nvoids.com
Please check the email id in the signature to reply to the correct email id.

HI everyone,
we have requirement on

1)Power Platform Developer
Sacramento, CA
- Power Apps, Dataverse, Power Automate, SharePoint

2 )Power BI Developer / BI Consultant
Sacramento, CA
- Power BI dashboards, data modeling, reporting/analytics

3) PPM Functional/Technical Consultant
Sacramento, CA
- Planner/Project, PPM workflows, resource management, implementation/training

--

Keywords: business intelligence information technology California
Requirement : Power Platform Developer : Sacramento, CA
ravisharpedge70@gmail.com

View this job online here

Happy recruiting
https://jobs.nvoids.com
Free resume and job search portal
"""

    result = parse_requirement_email(text)

    require(result["record_count"] == 3, f"Expected 3 separate positions, got {result['record_count']}: {result['records']}")

    titles = [r["job_title"] for r in result["records"]]
    require(
        titles == ["Power Platform Developer", "Power BI Developer / BI Consultant", "PPM Functional/Technical Consultant"],
        f"Wrong titles or wrong order: {titles}",
    )

    for record in result["records"]:
        require(
            "Keywords:" not in record["job_description"] and "jobs.nvoids.com" not in record["job_description"],
            f"The relay's footer boilerplate must never leak into a position's job_description: {record['job_description']!r}",
        )
        require(
            record["location"] == "Sacramento, CA",
            f"Every position must get the shared location, got {record['location']!r}",
        )


def test_single_numbered_bullet_does_not_trigger_multi_position_split() -> None:
    # A single position whose own requirements happen to be numbered
    # ("1) 5+ years Java") must not be mistaken for a second job.
    text = (
        "Job Title: Java Developer\n"
        "Required Skills: Java, Spring\n\n"
        "Requirements:\n"
        "1) 5+ years of Java experience\n"
        "Additional context about the one role, long enough to read as real body text here.\n"
    )

    result = parse_requirement_email(text)
    require(result["record_count"] == 1, f"A single numbered bullet must not split into multiple records: {result}")


def test_numbered_positions_skip_llm_fallback() -> None:
    from app.email_parsing.llm_fallback import apply_job_requirement_fallback

    text = (
        "We have two openings:\n\n"
        "1)Backend Engineer\nRemote\n- Java, Spring\n\n"
        "2)Frontend Engineer\nRemote\n- React, TypeScript\n"
    )
    result = parse_requirement_email(text)
    require(result["record_count"] == 2, f"Fixture must actually produce multiple records: {result}")

    updated, filled_fields = apply_job_requirement_fallback(text, result)
    require(filled_fields == set(), "The LLM fallback must never run against a multi-position result")
    require("llm_fallback" not in updated, "No llm_fallback metadata should be attached when the fallback was skipped")


def main() -> None:
    test_mailbox_routing()
    test_hotlist_parser()
    test_requirement_parser()
    test_confidence_based_classification()
    test_forwarded_requirement_with_end_client()
    test_nvoids_java_posting_regression()
    test_location_does_not_swallow_next_blank_label()
    test_security_gateway_banner_is_stripped()
    test_pipe_delimited_subject_still_yields_a_title()
    test_job_description_excludes_everything_from_the_signoff_onward()
    test_numbered_multi_position_email_splits_into_separate_records()
    test_single_numbered_bullet_does_not_trigger_multi_position_split()
    test_numbered_positions_skip_llm_fallback()

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
    print("PASS: security-gateway banner ([EXTERNAL]/CAUTION) is stripped from job_description")
    print("PASS: pipe-delimited subject ('Title | Location |') still yields a title")
    print("PASS: job_description excludes everything from the signoff onward, not just known footer markers")
    print("PASS: a numbered multi-position email splits into separate records, not one garbled record")
    print("PASS: a single position's own numbered bullets don't trigger a false multi-position split")
    print("PASS: multi-position results skip the single-record LLM fallback entirely")
    print("PASS: HERMES-850 parser guardrails")


if __name__ == "__main__":
    main()
