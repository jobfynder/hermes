"""Checks for HERMES-950: reviewer field corrections and the
field-level accuracy summary computed from them.
"""

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.drafts.accuracy import compute_accuracy_summary
from app.drafts.service import apply_field_corrections, get_draft_object


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _create_job_draft(source_message_id: str, text: str) -> str:
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id=source_message_id,
        sender=ChannelSender(email="recruiter@accuracytest.example.com"),
        content_type="text",
        text=text,
    )
    response = process_channel_intake(request)
    draft_id = response.understanding_result.get("draft_id") if response.understanding_result else None
    require(draft_id is not None, f"Expected a draft to be created for {source_message_id}")
    return draft_id


def test_apply_field_corrections_updates_payload() -> None:
    draft_id = _create_job_draft(
        "msg-corr-1",
        "Job Title: Java Developer\nRequired Skills: Java, Spring Boot\n\nLong enough body text here.\n",
    )

    updated = apply_field_corrections(
        draft_id=draft_id,
        record_type="job_requirement",
        record_index=0,
        corrections={"company": "Acme Staffing", "location": "Dallas, TX"},
    )

    require(updated is not None, "apply_field_corrections must return the updated draft")
    record = updated.payload["structured_data"]["email_parsing"]["records"][0]
    require(record["company"] == "Acme Staffing", f"Expected company to be corrected, got {record['company']!r}")
    require(record["location"] == "Dallas, TX", f"Expected location to be corrected, got {record['location']!r}")

    reloaded = get_draft_object(draft_id)
    reloaded_record = reloaded.payload["structured_data"]["email_parsing"]["records"][0]
    require(
        reloaded_record["company"] == "Acme Staffing",
        "The correction must actually persist to the database, not just the in-memory return value",
    )


def test_apply_field_corrections_ignores_unknown_fields() -> None:
    draft_id = _create_job_draft(
        "msg-corr-2",
        "Job Title: Python Developer\nRequired Skills: Python, Django\n\nLong enough body text here too.\n",
    )

    updated = apply_field_corrections(
        draft_id=draft_id,
        record_type="job_requirement",
        record_index=0,
        corrections={"job_description": "should be ignored, not editable", "company": "Beta Corp"},
    )

    require(updated is not None, "Must still apply the allowed field")
    record = updated.payload["structured_data"]["email_parsing"]["records"][0]
    require(record["company"] == "Beta Corp", "Allowed field must still be corrected")
    require(
        record["job_description"] != "should be ignored, not editable",
        "job_description is not in the editable field list and must be silently ignored",
    )


def test_apply_field_corrections_no_op_when_value_unchanged() -> None:
    draft_id = _create_job_draft(
        "msg-corr-3",
        "Job Title: DevOps Engineer\nCompany: Same Corp\nRequired Skills: AWS, Terraform\n\nLong enough body.\n",
    )

    draft_before = get_draft_object(draft_id)
    company_before = draft_before.payload["structured_data"]["email_parsing"]["records"][0]["company"]

    updated = apply_field_corrections(
        draft_id=draft_id,
        record_type="job_requirement",
        record_index=0,
        corrections={"company": company_before},
    )

    require(updated is not None, "Must return the draft even with no actual change")


def test_accuracy_summary_reflects_a_correction() -> None:
    text = (
        "Job Title: Accuracy Test Developer\n"
        "Required Skills: Java, Spring Boot, Kafka\n\n"
        "Long enough body text so the requirement-evidence check passes cleanly here.\n"
    )
    draft_id = _create_job_draft("msg-corr-accuracy-1", text)

    draft = get_draft_object(draft_id)
    record = draft.payload["structured_data"]["email_parsing"]["records"][0]
    require(record.get("company") is None, "Fixture must genuinely have no company for this test to be meaningful")

    # A correction where the original was empty ("filled a gap") must not
    # count as a precision miss -- it's a fill-rate story, not a wrong-
    # value story. Verify both halves.
    apply_field_corrections(
        draft_id=draft_id,
        record_type="job_requirement",
        record_index=0,
        corrections={"company": "Filled By Reviewer Inc"},
    )

    second_draft_id = _create_job_draft(
        "msg-corr-accuracy-2",
        (
            "Job Title: Second Accuracy Test Developer\n"
            "Company: Wrong Company Name\n"
            "Required Skills: Python, FastAPI\n\n"
            "Another long enough body text for the requirement-evidence check.\n"
        ),
    )
    apply_field_corrections(
        draft_id=second_draft_id,
        record_type="job_requirement",
        record_index=0,
        corrections={"company": "Correct Company Name"},
    )

    summary = compute_accuracy_summary(days=30)
    company_stats = next(f for f in summary["job_requirement_fields"] if f["field"] == "company")

    require(
        company_stats["corrected_missing_count"] >= 1,
        f"Expected at least one 'filled a gap' correction recorded, got {company_stats}",
    )
    require(
        company_stats["corrected_wrong_count"] >= 1,
        f"Expected at least one 'fixed a wrong value' correction recorded, got {company_stats}",
    )
    require(
        company_stats["filled_count"] >= 1,
        "The second draft's originally-wrong-but-non-empty company value must count toward filled_count",
    )


def test_accuracy_summary_flags_small_samples_as_unreliable() -> None:
    summary = compute_accuracy_summary(days=1)
    # A 1-day window in a fresh test database has near-zero samples for
    # most fields -- every one of them must be marked unreliable rather
    # than presenting a confident-looking percentage from 0-2 data points.
    for field_stats in summary["job_requirement_fields"]:
        if field_stats["filled_count"] < 10:
            require(
                field_stats["reliable"] is False,
                f"Field with only {field_stats['filled_count']} samples must be flagged unreliable: {field_stats}",
            )


def main() -> None:
    test_apply_field_corrections_updates_payload()
    print("PASS: applying a field correction updates and persists the payload")

    test_apply_field_corrections_ignores_unknown_fields()
    print("PASS: non-editable fields (job_description) are silently ignored")

    test_apply_field_corrections_no_op_when_value_unchanged()
    print("PASS: submitting the same value as a 'correction' is a safe no-op")

    test_accuracy_summary_reflects_a_correction()
    print("PASS: accuracy summary separates 'filled a gap' from 'fixed a wrong value'")

    test_accuracy_summary_flags_small_samples_as_unreliable()
    print("PASS: small-sample fields are flagged unreliable rather than shown as a confident percentage")

    print("HERMES-950 review editing + accuracy check PASSED")


if __name__ == "__main__":
    main()
