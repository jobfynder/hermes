from app.email_parsing.provenance import (
    build_email_parsing_provenance,
    load_field_provenance,
    record_field_provenance,
    record_recruiter_correction,
)
from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_job_requirement_fields_get_provenance_rows() -> None:
    email_parsing = {
        "parser": {"name": "hermes_email_deterministic_parser"},
        "document_kind": "job_description",
        "records": [
            {
                "job_title": "Java Developer",
                "job_description": "5+ years Java, Spring Boot, AWS",
                "required_skills": ["Java", "Spring Boot"],
                "preferred_skills": [],
                "years_of_experience": 5,
                "location": "Dallas, TX",
                "work_authorization": None,
                "employment_type": "Contract",
                "rate_or_salary": "$70/hr",
                "parse_confidence": 0.92,
            }
        ],
    }

    entries = build_email_parsing_provenance(email_parsing)
    by_path = {entry["field_path"]: entry for entry in entries}

    require("job.job_title" in by_path, "Expected job.job_title provenance entry")
    require(by_path["job.job_title"]["value_kind"] == "EXTRACTED", "Present field must be EXTRACTED")
    require(by_path["job.work_authorization"]["value_kind"] == "UNKNOWN", "Null field must be UNKNOWN, not guessed")
    require(by_path["job.job_title"]["extraction_method"] == "deterministic", "Must record deterministic, not LLM")
    require(abs(by_path["job.job_title"]["confidence"] - 0.92) < 1e-9, "Must carry the record's parse confidence")


def test_recruiter_correction_is_a_new_row_not_an_overwrite() -> None:
    parse_run_id = "test-parse-run-correction"
    record_field_provenance(
        parse_run_id,
        [
            {
                "field_path": "job.location",
                "raw_value": "Dallas",
                "normalized_value": "Dallas",
                "source_region": None,
                "extractor": "hermes_email_deterministic_parser",
                "extraction_method": "deterministic",
                "confidence": 0.9,
                "value_kind": "EXTRACTED",
            }
        ],
    )

    record_recruiter_correction(parse_run_id, "job.location", before="Dallas", after="Dallas, TX (Hybrid)")

    rows = load_field_provenance(parse_run_id)
    location_rows = [row for row in rows if row["field_path"] == "job.location"]

    require(len(location_rows) == 2, "Correction must add a row, not overwrite the original")
    require(
        location_rows[0]["extractor"] == "hermes_email_deterministic_parser",
        "Original deterministic row must survive unchanged",
    )
    require(
        location_rows[1]["extractor"] == "recruiter_correction",
        "Correction row must be tagged extractor=recruiter_correction",
    )
    require(location_rows[1]["raw_value"] == "Dallas", "Correction row must record the pre-correction value")
    require(
        location_rows[1]["normalized_value"] == "Dallas, TX (Hybrid)",
        "Correction row must record the recruiter's corrected value",
    )


def test_intake_persists_provenance_for_the_created_draft() -> None:
    result = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="provenance-source-1",
            content_type="text",
            text=(
                "Job Title: Cloud Engineer\n"
                "Required Skills: Azure, Terraform, Kubernetes\n"
                "Location: Remote\n"
                "Rate: $80/hr\n"
            ),
        )
    )

    draft_id = result.understanding_result["draft_id"]
    rows = load_field_provenance(draft_id)

    require(len(rows) > 0, "Intake must persist field-level provenance for the created draft")
    require(
        any(row["field_path"] == "job.job_title" for row in rows),
        "Expected a job.job_title provenance row from real intake",
    )


if __name__ == "__main__":
    test_job_requirement_fields_get_provenance_rows()
    test_recruiter_correction_is_a_new_row_not_an_overwrite()
    test_intake_persists_provenance_for_the_created_draft()
    print("hermes-850-provenance-check: all checks passed")
