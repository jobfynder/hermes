"""Checks for apply_signature_company_fill (app/email_parsing/parsers.py)
and its wiring into process_channel_intake (app/channels/service.py).

Standing cost policy: LLM fallback (app/email_parsing/llm_fallback.py) is
a last resort on high-volume regular traffic, never the first move. This
gap-fill resolves the single largest requires_review driver (company
missing on an otherwise-complete job requirement -- HERMES-950's
review-queue report showed it as 67% of all review warnings) using a
value Hermes' own deterministic signature parser already extracted, at
zero additional cost -- and it must run before the LLM fallback so a
successful fill actually skips that LLM call, not just adds a redundant
value.
"""
from unittest.mock import patch

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.email_parsing.parsers import apply_signature_company_fill
from app.email_parsing.provenance import build_email_parsing_provenance


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _job_record(**overrides) -> dict:
    record = {
        "record_type": "job_requirement",
        "job_title": "Java Developer",
        "job_description": "5+ years Java, Spring Boot",
        "company": None,
        "linkedin_url": None,
        "required_skills": ["Java", "Spring Boot"],
        "preferred_skills": [],
        "years_of_experience": 5,
        "location": "Dallas, TX",
        "work_authorization": None,
        "employment_type": None,
        "rate_or_salary": None,
        "source_section": 1,
        "parse_confidence": 0.65,
        "requires_review": True,
        "warnings": ["company_missing"],
    }
    record.update(overrides)
    return record


def test_fills_company_from_detected_signature_and_clears_review() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.65,
        "records": [_job_record()],
    }
    signature = {
        "detected": True,
        "contact": {"company_name": {"value": "Indus River Technologies", "confidence": 0.8}},
    }

    result, filled = apply_signature_company_fill(email_parsing, signature)

    require(filled is True, "Must report that it filled the gap")
    record = result["records"][0]
    require(record["company"] == "Indus River Technologies", f"Company was not filled: {record}")
    require(record["parse_confidence"] >= 0.92, f"Title+skills+company must score high, got {record['parse_confidence']}")
    require(record["requires_review"] is False, "A now-complete record must no longer require review")
    require("company_missing" not in record["warnings"], "Stale company_missing warning must be cleared")
    require(result["requires_review"] is False, "Whole-email requires_review must follow the record")
    require(result["signature_filled_fields"] == ["company"], "Must report company as signature-filled")


def test_never_overrides_a_company_the_deterministic_parser_already_found() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.92,
        "records": [_job_record(company="Acme Staffing", parse_confidence=0.92, requires_review=False, warnings=[])],
    }
    signature = {"detected": True, "contact": {"company_name": {"value": "Some Other Company"}}}

    result, filled = apply_signature_company_fill(email_parsing, signature)

    require(filled is False, "Must not report a fill when company was already present")
    require(result["records"][0]["company"] == "Acme Staffing", "Existing deterministic value must never be overwritten")


def test_no_signature_company_leaves_result_unchanged() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.65,
        "records": [_job_record()],
    }
    signature = {"detected": False, "contact": {}}

    result, filled = apply_signature_company_fill(email_parsing, signature)

    require(filled is False, "Nothing to fill when the signature has no company")
    require(result["records"][0]["company"] is None, "Company must stay null, not guessed")
    require(result["records"][0]["requires_review"] is True, "Must still require review")


def test_multi_position_email_is_left_for_a_human_same_as_llm_fallback() -> None:
    """Same restriction apply_job_requirement_fallback already applies
    (app/email_parsing/llm_fallback.py) -- a sender's signature only
    names one company/agency, but a bundled multi-position email's
    positions can genuinely be for different end clients.
    """
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.65,
        "records": [_job_record(source_section=1), _job_record(source_section=2)],
    }
    signature = {"detected": True, "contact": {"company_name": {"value": "Indus River Technologies"}}}

    result, filled = apply_signature_company_fill(email_parsing, signature)

    require(filled is False, "Multi-position emails must never get an auto-filled company")
    require(all(r["company"] is None for r in result["records"]), "No position's company may be guessed")


def test_deterministic_fill_skips_the_llm_call_entirely() -> None:
    """End-to-end: a job requirement email whose body never states a
    company, but whose signature does, must clear FALLBACK_CONFIDENCE_
    THRESHOLD from the signature fill alone and never invoke the LLM.
    """
    text = (
        "Job Title: Senior Java Developer\n"
        "Required Skills: Java, Spring Boot, Kafka\n\n"
        "Hi, hope you're doing well. We have an urgent opening, please "
        "let me know if you or your consultants are interested.\n\n"
        "Regards,\n"
        "Priya Sharma\n"
        "Senior Technical Recruiter\n"
        "Indus River Technologies\n"
        "priya.sharma@indusrivertech-example.com\n"
        "(555) 987-6543\n"
    )

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        result = process_channel_intake(
            ChannelIntakeRequest(
                channel="email",
                source_message_id="signature-company-fill-e2e-1",
                sender=ChannelSender(email="priya.sharma@indusrivertech-example.com"),
                content_type="text",
                text=text,
            )
        )

    require(not mock_run.called, "A signature-resolvable company gap must never reach the LLM fallback")
    structured = result.understanding_result.get("structured_data", {})
    record = structured.get("email_parsing", {}).get("records", [{}])[0]
    require(record.get("company") == "Indus River Technologies", f"Company was not filled from the signature: {record}")
    require(result.requires_review is False, "A fully-resolved requirement must not require review")


def test_provenance_tags_signature_filled_company_distinctly() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "parser": {"name": "hermes_email_deterministic_parser"},
        "signature_filled_fields": ["company"],
        "records": [_job_record(company="Indus River Technologies", parse_confidence=0.92, requires_review=False, warnings=[])],
    }

    entries = build_email_parsing_provenance(email_parsing)
    by_path = {e["field_path"]: e for e in entries}

    require(by_path["job.company"]["extraction_method"] == "signature_fill", "Must be tagged signature_fill, not deterministic or llm_fallback")
    require(by_path["job.company"]["extractor"] == "hermes_email_signature_parser", f"Wrong extractor tag: {by_path['job.company']}")
    require(by_path["job.company"]["value_kind"] == "EXTRACTED", "signature_fill is not an LLM extraction -- must stay EXTRACTED, not LLM_EXTRACTED")
    require(by_path["job.job_title"]["extraction_method"] == "deterministic", "Untouched field must stay deterministic")


if __name__ == "__main__":
    test_fills_company_from_detected_signature_and_clears_review()
    print("PASS: signature-detected company fills the gap and clears requires_review")

    test_never_overrides_a_company_the_deterministic_parser_already_found()
    print("PASS: never overrides a company the deterministic parser already found")

    test_no_signature_company_leaves_result_unchanged()
    print("PASS: no signature company leaves the record honestly incomplete")

    test_multi_position_email_is_left_for_a_human_same_as_llm_fallback()
    print("PASS: multi-position emails are never auto-filled from the signature")

    test_deterministic_fill_skips_the_llm_call_entirely()
    print("PASS: a signature-resolvable company gap never reaches the LLM fallback")

    test_provenance_tags_signature_filled_company_distinctly()
    print("PASS: signature-filled company is tagged distinctly in provenance")

    print("hermes-850-signature-company-fill-check: all checks passed")
