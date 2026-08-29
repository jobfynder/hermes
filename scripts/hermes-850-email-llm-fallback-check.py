"""Checks for app/email_parsing/llm_fallback.py -- the confidence-gated
LLM extraction fallback for email parsing (spec section 7.5 step 7).

run_llm_fallback (app/prompt_runtime/extraction_fallback.py) is mocked
throughout: these checks verify the *gating and merge logic* in this
module, not the real LiteLLM/Langfuse call, which costs real money and
belongs to that module's own test coverage, not this one's.
"""
from unittest.mock import patch

from app.email_parsing.llm_fallback import (
    JOB_FALLBACK_PROMPT_ID,
    HOTLIST_FALLBACK_PROMPT_ID,
    apply_hotlist_fallback,
    apply_job_requirement_fallback,
)
from app.email_parsing.provenance import build_email_parsing_provenance


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_high_confidence_job_never_calls_fallback() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.92,
        "records": [{"job_title": "Java Developer", "parse_confidence": 0.92}],
    }

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        result, filled = apply_job_requirement_fallback("some text", email_parsing)

    require(not mock_run.called, "High-confidence deterministic parse must never call the LLM fallback")
    require(filled == set(), "No fields should be reported as LLM-filled")
    require(result["records"][0]["job_title"] == "Java Developer", "Record must be untouched")


def test_low_confidence_job_fills_only_empty_fields() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.35,
        "records": [
            {
                "job_title": "QA Engineer",  # already found deterministically
                "required_skills": [],  # empty -- eligible for fallback fill
                "location": None,  # empty -- eligible for fallback fill
                "rate_or_salary": None,
                "employment_type": None,
                "work_authorization": None,
                "years_of_experience": None,
                "preferred_skills": [],
                "parse_confidence": 0.35,
            }
        ],
    }

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        mock_run.return_value = {
            "used": True,
            "prompt_id": JOB_FALLBACK_PROMPT_ID,
            "extracted": {
                "job_title": "Something Else Entirely",  # must NOT overwrite the deterministic hit
                "required_skills": ["Selenium", "Java"],
                "location": "Remote",
                "rate_or_salary": None,  # LLM found nothing either -- must stay null, not guessed
            },
        }
        result, filled = apply_job_requirement_fallback("clean text", email_parsing)

    require(mock_run.called, "Low-confidence parse must call the LLM fallback")
    call_kwargs = mock_run.call_args.kwargs
    require(call_kwargs["prompt_id"] == JOB_FALLBACK_PROMPT_ID, "Must use the existing jf.jobs.jd.extract prompt")

    record = result["records"][0]
    require(
        record["job_title"] == "QA Engineer",
        "A field the deterministic parser already found must never be overwritten by the LLM",
    )
    require(record["required_skills"] == ["Selenium", "Java"], "Empty field must be filled from the LLM result")
    require(record["location"] == "Remote", "Empty field must be filled from the LLM result")
    require(record["rate_or_salary"] is None, "A field the LLM also could not find must stay null, not guessed")
    require(filled == {"required_skills", "location"}, f"Wrong filled-fields set: {filled}")
    require(record["parse_confidence"] >= 0.75, "Confidence must rise once the LLM contributed real fields")


def test_llm_fallback_not_used_leaves_result_unchanged() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "confidence": 0.2,
        "records": [{"job_title": None, "parse_confidence": 0.2, "required_skills": []}],
    }

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        mock_run.return_value = {"used": False, "reason": "llm_fallback_disabled_by_config"}
        result, filled = apply_job_requirement_fallback("text", email_parsing)

    require(filled == set(), "Nothing should be reported filled when the fallback call itself failed")
    require(result["confidence"] == 0.2, "Confidence must not change when the fallback produced nothing")
    require(result["llm_fallback"]["used"] is False, "Outcome must be recorded even when unused, for observability")


def test_empty_job_records_get_a_stub_to_fill() -> None:
    """spec 7.5: LLM fallback also triggers when deterministic parsing
    'fails to extract required fields entirely', not just when it found
    a record with some fields missing."""
    email_parsing = {"document_kind": "job_description", "confidence": 0.0, "records": []}

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        mock_run.return_value = {
            "used": True,
            "prompt_id": JOB_FALLBACK_PROMPT_ID,
            "extracted": {"job_title": "DevOps Engineer", "location": "Austin, TX"},
        }
        result, filled = apply_job_requirement_fallback("text", email_parsing)

    require(len(result["records"]) == 1, "An empty deterministic result must still produce one record to fill")
    require(result["records"][0]["job_title"] == "DevOps Engineer", "Stub record must be filled from the LLM")
    require("job_title" in filled and "location" in filled, f"Wrong filled set: {filled}")


def test_low_confidence_hotlist_replaces_records() -> None:
    email_parsing = {
        "document_kind": "hotlist",
        "confidence": 0.15,
        "records": [{"candidate_name": None, "parse_confidence": 0.15}],  # wrong split
    }

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        mock_run.return_value = {
            "used": True,
            "prompt_id": HOTLIST_FALLBACK_PROMPT_ID,
            "extracted": {
                "consultants": [
                    {"candidate_name": "Jane Doe", "primary_job_title": "Java Developer", "primary_skills": ["Java"]},
                    {"candidate_name": "John Smith", "primary_job_title": "Python Developer", "primary_skills": ["Python"]},
                ]
            },
        }
        result, used = apply_hotlist_fallback("text", email_parsing)

    require(used, "LLM hotlist fallback must report it was used")
    call_kwargs = mock_run.call_args.kwargs
    require(call_kwargs["prompt_id"] == HOTLIST_FALLBACK_PROMPT_ID, "Must reuse the existing broadcast hotlist prompt")
    require(result["record_count"] == 2, "Wrong split must be replaced by the LLM's own consultant boundaries")
    require(result["records"][0]["candidate_name"] == "Jane Doe", "Wrong content in replaced records")
    require(result["records"][1]["candidate_name"] == "John Smith", "Wrong content in replaced records")
    require(result["confidence"] >= 0.75, "Confidence must rise once the LLM produced a usable split")


def test_hotlist_fallback_no_consultants_leaves_original() -> None:
    email_parsing = {
        "document_kind": "hotlist",
        "confidence": 0.1,
        "records": [{"candidate_name": None, "parse_confidence": 0.1}],
    }

    with patch("app.email_parsing.llm_fallback.run_llm_fallback") as mock_run:
        mock_run.return_value = {"used": True, "extracted": {"consultants": []}}
        result, used = apply_hotlist_fallback("text", email_parsing)

    require(not used, "An LLM result with zero consultants must not replace the original records")
    require(result["records"][0]["candidate_name"] is None, "Original (wrong) record must be left as-is, not discarded")


def test_provenance_tags_llm_filled_fields_distinctly() -> None:
    email_parsing = {
        "document_kind": "job_description",
        "parser": {"name": "hermes_email_deterministic_parser"},
        "llm_filled_fields": ["location", "required_skills"],
        "records": [
            {
                "job_title": "QA Engineer",  # deterministic
                "location": "Remote",  # llm-filled
                "required_skills": ["Selenium"],  # llm-filled
                "job_description": None,
                "preferred_skills": [],
                "years_of_experience": None,
                "work_authorization": None,
                "employment_type": None,
                "rate_or_salary": None,
                "parse_confidence": 0.75,
            }
        ],
    }

    entries = build_email_parsing_provenance(email_parsing)
    by_path = {e["field_path"]: e for e in entries}

    require(by_path["job.job_title"]["extraction_method"] == "deterministic", "Untouched field must stay deterministic")
    require(by_path["job.job_title"]["value_kind"] == "EXTRACTED", "Deterministic present field must be EXTRACTED")
    require(by_path["job.location"]["extraction_method"] == "llm_fallback", "Filled field must be tagged llm_fallback")
    require(by_path["job.location"]["value_kind"] == "LLM_EXTRACTED", "Filled field must be LLM_EXTRACTED, not plain EXTRACTED")
    require(by_path["job.location"]["extractor"] == JOB_FALLBACK_PROMPT_ID, "Filled field's extractor must be the prompt id")
    require(by_path["job.rate_or_salary"]["value_kind"] == "UNKNOWN", "Still-null field must stay UNKNOWN even after a fallback pass")


def test_provenance_tags_whole_hotlist_records_as_llm_when_used() -> None:
    email_parsing = {
        "document_kind": "hotlist",
        "parser": {"name": "hermes_email_deterministic_parser"},
        "llm_fallback": {"used": True},
        "records": [
            {
                "candidate_name": "Jane Doe",
                "primary_job_title": "Java Developer",
                "primary_skills": ["Java"],
                "candidate_email": None,
                "candidate_phone": None,
                "years_of_experience": None,
                "current_location": None,
                "work_authorization": None,
                "availability": None,
                "expected_rate": None,
                "source_row": 1,
                "parse_confidence": 0.75,
            }
        ],
    }

    entries = build_email_parsing_provenance(email_parsing)
    by_path = {e["field_path"]: e for e in entries}

    require(
        by_path["consultant.1.candidate_name"]["extraction_method"] == "llm_fallback",
        "Every field of an LLM-replaced hotlist record must be tagged llm_fallback",
    )
    require(by_path["consultant.1.candidate_name"]["extractor"] == HOTLIST_FALLBACK_PROMPT_ID, "Wrong extractor tag")


if __name__ == "__main__":
    test_high_confidence_job_never_calls_fallback()
    test_low_confidence_job_fills_only_empty_fields()
    test_llm_fallback_not_used_leaves_result_unchanged()
    test_empty_job_records_get_a_stub_to_fill()
    test_low_confidence_hotlist_replaces_records()
    test_hotlist_fallback_no_consultants_leaves_original()
    test_provenance_tags_llm_filled_fields_distinctly()
    test_provenance_tags_whole_hotlist_records_as_llm_when_used()
    print("hermes-850-email-llm-fallback-check: all checks passed")
