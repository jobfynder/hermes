"""Checks for app/integrations/core_job_push.py -- the last step of the
pipeline, pushing a PUBLISHED job-requirement draft to Jobfynder Core's
job board. The real HTTP call (urlopen) is mocked throughout -- these
checks verify the field mapping and the never-raises/always-recorded
contract, not connectivity to the real uat.jobfynder.com, which belongs
to a live-environment check, not an automated regression script.
"""
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

from app.drafts.service import create_draft_object, publish_draft_object
from app.integrations.core_job_push import (
    _parse_location,
    _parse_rate,
    map_draft_to_core_job_payload,
    push_job_to_core,
)
from app.runtime.db import cursor


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_parse_rate_hourly() -> None:
    result = _parse_rate("$65/hr")
    require(result.get("minRate") == 65.0, f"Wrong minRate: {result}")
    require(result.get("rateType") == "PER_HOUR", f"Wrong rateType: {result}")
    require("maxRate" not in result, f"Single-value rate must not set maxRate: {result}")


def test_parse_rate_range() -> None:
    result = _parse_rate("$70-80/hr")
    require(result.get("minRate") == 70.0, f"Wrong minRate: {result}")
    require(result.get("maxRate") == 80.0, f"Wrong maxRate: {result}")


def test_parse_rate_annual_k() -> None:
    result = _parse_rate("$120k/year")
    require(result.get("minRate") == 120000.0, f"Wrong minRate for 'k' suffix: {result}")
    require(result.get("rateType") == "ANNUAL", f"Wrong rateType: {result}")


def test_parse_rate_unparseable_returns_empty() -> None:
    require(_parse_rate("negotiable") == {}, "Unparseable rate text must yield an empty dict, not guess")
    require(_parse_rate(None) == {}, "None must yield an empty dict")


def test_parse_location_with_work_mode() -> None:
    result = _parse_location("Burlington, MA (100% Onsite)")
    require(result["city"] == "Burlington", f"Wrong city: {result}")
    require(result["state"] == "MA", f"Wrong state: {result}")
    require(result["workLocation"] == "ONSITE", f"Wrong workLocation: {result}")


def test_parse_location_remote_defaults_no_city() -> None:
    result = _parse_location("Fully Remote")
    require(result["workLocation"] == "REMOTE", f"Wrong workLocation: {result}")


def test_parse_location_unknown_mode_defaults_onsite() -> None:
    result = _parse_location("Dallas, TX")
    require(result["workLocation"] == "ONSITE", "No work-mode signal must default to ONSITE, Core's most common case")


def _job_draft(**overrides):
    payload = {
        "text": "raw email text",
        "structured_data": {
            "email_parsing": {
                "records": [
                    {
                        "job_title": "Java Developer",
                        "job_description": "5+ years Java",
                        "required_skills": ["Java", "Spring Boot"],
                        "preferred_skills": ["AWS"],
                        "years_of_experience": 5,
                        "location": "Dallas, TX (Onsite)",
                        "work_authorization": "H1B",
                        "employment_type": "Contract",
                        "rate_or_salary": "$70/hr",
                    }
                ]
            }
        },
    }
    metadata = {"sender": {"email": "recruiter@staffingco.com", "sender_name": "Jane Recruiter"}}
    metadata.update(overrides.pop("metadata", {}))

    return create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload=payload,
        confidence=0.9,
        requires_review=False,
        metadata=metadata,
        **overrides,
    )


def test_map_draft_basic_fields() -> None:
    draft = _job_draft()
    payload = map_draft_to_core_job_payload(draft)

    require(payload["jobTitle"] == "Java Developer", f"Wrong jobTitle: {payload}")
    require(payload["city"] == "Dallas", f"Wrong city: {payload}")
    require(payload["workLocation"] == "ONSITE", f"Wrong workLocation: {payload}")
    require(payload["minRate"] == 70.0, f"Wrong minRate: {payload}")
    require(payload["employmentTypes"] == ["Contract"], f"Wrong employmentTypes: {payload}")
    require(payload["workAuthorizations"] == ["H1B"], f"Wrong workAuthorizations: {payload}")
    require(set(payload["primarySkills"]) == {"Java", "Spring Boot"}, f"Wrong primarySkills: {payload}")
    require(set(payload["skills"]) == {"Java", "Spring Boot", "AWS"}, f"Wrong skills: {payload}")
    require(payload["externalSource"]["recruiterEmail"] == "recruiter@staffingco.com", f"Wrong externalSource: {payload}")
    require(payload["externalSource"]["sourceType"] == "EMAIL", f"Wrong sourceType: {payload}")


def test_map_draft_missing_employment_type_omits_field() -> None:
    """Core requires at least one employment type -- Hermes must never
    invent one just to fill the field. An absent value stays absent,
    letting Core's own required-field check fail loudly and visibly
    rather than Hermes silently guessing 'Contract'."""
    draft = _job_draft()
    draft.payload["structured_data"]["email_parsing"]["records"][0]["employment_type"] = None
    payload = map_draft_to_core_job_payload(draft)
    require("employmentTypes" not in payload, f"Must not invent an employment type: {payload}")


def test_map_draft_claimed_fields_override_raw_parse() -> None:
    draft = _job_draft()
    draft.metadata["claimed_fields"] = {"job_title": "Senior Java Developer (Corrected)", "location": "Remote"}
    payload = map_draft_to_core_job_payload(draft)

    require(
        payload["jobTitle"] == "Senior Java Developer (Corrected)",
        "A recruiter's claimed correction must override the raw deterministic parse",
    )
    require(payload["workLocation"] == "REMOTE", "Claimed location correction must also override")


def test_push_skips_non_job_requirement_drafts() -> None:
    draft = create_draft_object(
        draft_type="draft_hotlist",
        source="channel_text_intake",
        payload={"text": "a hotlist"},
        confidence=0.9,
        requires_review=False,
    )
    result = push_job_to_core(draft)
    require(result["status"] == "skipped", f"Hotlist drafts must never be pushed to the job board: {result}")


def _fake_http_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    return io.BytesIO(body)


def test_push_success_records_core_job_id() -> None:
    draft = _job_draft()

    with patch("app.integrations.core_job_push.core_push_configured", return_value=True), \
         patch("app.integrations.core_job_push.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = _fake_http_response(
            {"data": {"job_id": "core-job-123", "job_url": "https://uat.jobfynder.com/jobs/xyz"}}
        )
        result = push_job_to_core(draft)

    require(result["status"] == "pushed", f"Expected a successful push: {result}")
    require(result["core_job_id"] == "core-job-123", f"Wrong core_job_id: {result}")

    with cursor() as cur:
        cur.execute("SELECT * FROM core_pushes WHERE draft_id = %s ORDER BY id DESC LIMIT 1", (draft.draft_id,))
        row = cur.fetchone()
    require(row is not None, "Successful push must be recorded in core_pushes")
    require(row["status"] == "pushed", f"Wrong recorded status: {row}")
    require(row["core_job_id"] == "core-job-123", f"Wrong recorded core_job_id: {row}")


def test_push_http_error_never_raises_and_is_recorded() -> None:
    draft = _job_draft()

    with patch("app.integrations.core_job_push.core_push_configured", return_value=True), \
         patch("app.integrations.core_job_push.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError(
            url="https://uat.jobfynder.com/api/hermes/job/create",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"At least one valid employment type is required"}'),
        )
        result = push_job_to_core(draft)

    require(result["status"] == "failed", f"An HTTP error must be reported as failed, not raised: {result}")
    require("http_400" in result["reason"], f"Wrong reason: {result}")

    with cursor() as cur:
        cur.execute("SELECT * FROM core_pushes WHERE draft_id = %s ORDER BY id DESC LIMIT 1", (draft.draft_id,))
        row = cur.fetchone()
    require(row is not None and row["status"] == "failed", f"Failed push must still be recorded: {row}")


def test_push_not_configured_fails_gracefully() -> None:
    draft = _job_draft()

    with patch("app.integrations.core_job_push.core_push_configured", return_value=False):
        result = push_job_to_core(draft)

    require(result["status"] == "failed", f"Unconfigured push must report failed, not silently succeed: {result}")
    require(result["reason"] == "core_push_not_configured", f"Wrong reason: {result}")


def test_publish_draft_object_pushes_and_survives_push_failure() -> None:
    """The whole point of 'never raises': a Core outage or a bad token
    must never turn a successful Hermes-side publish into a failure."""
    draft = _job_draft()

    with patch("app.integrations.core_job_push.core_push_configured", return_value=True), \
         patch("app.integrations.core_job_push.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError(
            url="x", code=500, msg="Internal Server Error", hdrs=None, fp=io.BytesIO(b"{}")
        )
        result = publish_draft_object(draft.draft_id)

    require(result.status == "published", f"Publish must succeed in Hermes even when the Core push fails: {result}")

    with cursor() as cur:
        cur.execute("SELECT metadata FROM drafts WHERE draft_id = %s", (draft.draft_id,))
        row = cur.fetchone()
    require(
        row["metadata"].get("core_push", {}).get("status") == "failed",
        f"The failed push outcome must still be recorded on the draft: {row['metadata']}",
    )


if __name__ == "__main__":
    test_parse_rate_hourly()
    test_parse_rate_range()
    test_parse_rate_annual_k()
    test_parse_rate_unparseable_returns_empty()
    test_parse_location_with_work_mode()
    test_parse_location_remote_defaults_no_city()
    test_parse_location_unknown_mode_defaults_onsite()
    test_map_draft_basic_fields()
    test_map_draft_missing_employment_type_omits_field()
    test_map_draft_claimed_fields_override_raw_parse()
    test_push_skips_non_job_requirement_drafts()
    test_push_success_records_core_job_id()
    test_push_http_error_never_raises_and_is_recorded()
    test_push_not_configured_fails_gracefully()
    test_publish_draft_object_pushes_and_survives_push_failure()
    print("hermes-850-core-job-push-check: all checks passed")
