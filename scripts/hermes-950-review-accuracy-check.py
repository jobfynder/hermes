"""Checks for HERMES-950: reviewer field corrections and the
field-level accuracy summary computed from them.
"""

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.drafts.accuracy import compute_accuracy_summary
from app.drafts.service import apply_field_corrections, get_draft_object
from app.email_parsing.signature_learning import apply_learned_signature_patterns, record_signature_correction
from app.runtime.db import cursor


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


def _create_signed_job_draft(source_message_id: str, sender_email: str, signature_block: str) -> str:
    text = (
        "Job Title: Signature Test Developer\n"
        "Required Skills: Java, Spring Boot\n\n"
        "Long enough body text here for the requirement-evidence check.\n\n"
        f"{signature_block}"
    )
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id=source_message_id,
        sender=ChannelSender(email=sender_email),
        content_type="text",
        text=text,
    )
    response = process_channel_intake(request)
    draft_id = response.understanding_result.get("draft_id") if response.understanding_result else None
    require(draft_id is not None, f"Expected a draft to be created for {source_message_id}")
    return draft_id


_SIGNATURE_WITH_COMPANY = """Regards,
Priya Sharma
Senior Technical Recruiter
Signature Test Staffing LLC
priya.sharma@sigtest-domain.example.com
(555) 987-6543
"""


def test_edit_signature_field_persists_and_is_tracked() -> None:
    draft_id = _create_signed_job_draft(
        "msg-sig-corr-1", "priya.sharma@sigtest-domain.example.com", _SIGNATURE_WITH_COMPANY
    )
    draft = get_draft_object(draft_id)
    contact = draft.payload["structured_data"]["signature"]["contact"]
    require("company_name" in contact, f"Fixture must have a detected company_name for this test: {contact}")

    updated = apply_field_corrections(
        draft_id=draft_id,
        record_type="signature",
        record_index=0,
        corrections={"company_name": "Corrected Staffing Name Inc"},
    )

    require(updated is not None, "Correcting a detected signature field must succeed")
    updated_contact = updated.payload["structured_data"]["signature"]["contact"]
    require(
        updated_contact["company_name"]["value"] == "Corrected Staffing Name Inc",
        f"Expected the corrected company name, got {updated_contact['company_name']}",
    )
    require(
        updated_contact["company_name"]["method"] == "human_edited",
        "A corrected signature field must be stamped as human_edited",
    )

    reloaded = get_draft_object(draft_id)
    reloaded_contact = reloaded.payload["structured_data"]["signature"]["contact"]
    require(
        reloaded_contact["company_name"]["value"] == "Corrected Staffing Name Inc",
        "The signature correction must actually persist to the database",
    )


def test_edit_signature_field_ignores_fields_the_parser_never_detected() -> None:
    draft_id = _create_signed_job_draft(
        "msg-sig-corr-2", "priya.sharma@sigtest-domain.example.com", _SIGNATURE_WITH_COMPANY
    )

    updated = apply_field_corrections(
        draft_id=draft_id,
        record_type="signature",
        record_index=0,
        corrections={"not_a_real_signature_field": "should be dropped"},
    )

    require(updated is not None, "Must still return the draft even when every key is dropped")
    contact = updated.payload["structured_data"]["signature"]["contact"]
    require(
        "not_a_real_signature_field" not in contact,
        "A field the signature parser never produced must not be injectable via a correction",
    )


def test_signature_correction_learned_and_applied_to_next_email_from_same_domain() -> None:
    first_draft_id = _create_signed_job_draft(
        "msg-sig-learn-1", "recruiter@learn-pattern.example.com", _SIGNATURE_WITH_COMPANY
    )
    apply_field_corrections(
        draft_id=first_draft_id,
        record_type="signature",
        record_index=0,
        corrections={"company_name": "Learned Pattern Staffing Co"},
    )

    # A second email from the SAME domain whose signature has no company
    # line at all -- the parser genuinely can't detect one.
    second_draft_id = _create_signed_job_draft(
        "msg-sig-learn-2",
        "another.recruiter@learn-pattern.example.com",
        "Thanks,\nAlex Recruiter\nalex.recruiter@learn-pattern.example.com\n",
    )

    draft = get_draft_object(second_draft_id)
    contact = draft.payload["structured_data"]["signature"]["contact"]
    require(
        contact.get("company_name", {}).get("value") == "Learned Pattern Staffing Co",
        f"The domain's previously-corrected company name must auto-fill the gap: {contact.get('company_name')}",
    )
    require(
        contact["company_name"]["method"] == "learned_from_domain_pattern",
        f"Must be tagged as learned, not a fresh deterministic extraction: {contact['company_name']}",
    )


def test_signature_learning_never_overrides_a_field_the_parser_did_detect() -> None:
    first_draft_id = _create_signed_job_draft(
        "msg-sig-learn-noverride-1", "recruiter@noverride-pattern.example.com", _SIGNATURE_WITH_COMPANY
    )
    apply_field_corrections(
        draft_id=first_draft_id,
        record_type="signature",
        record_index=0,
        corrections={"company_name": "Should Never Appear Here"},
    )

    # A second email from the same domain that DOES have its own,
    # different, genuinely detectable company name.
    second_signature = """Regards,
Sam Recruiter
Noverride Pattern Consulting
sam.recruiter@noverride-pattern.example.com
"""
    second_draft_id = _create_signed_job_draft(
        "msg-sig-learn-noverride-2", "sam.recruiter@noverride-pattern.example.com", second_signature
    )

    draft = get_draft_object(second_draft_id)
    contact = draft.payload["structured_data"]["signature"]["contact"]
    require(
        contact["company_name"]["value"] == "Noverride Pattern Consulting",
        f"A value the parser actually detected must never be overridden by a learned pattern: {contact['company_name']}",
    )


def test_signature_learning_never_records_or_applies_a_freemail_domain() -> None:
    """Regression test for a real production incident: a single
    correction learned for one gmail.com sender got applied to 700+
    unrelated drafts from other people who also happen to use gmail.com,
    because a job-board relay sends on behalf of many different
    recruiters through their own personal addresses. A sender domain only
    identifies one company for a real corporate domain, never a shared
    public mail provider.
    """
    record_signature_correction("gmail.com", "company_name", "Should Never Be Recorded")

    with cursor() as cur:
        cur.execute(
            "SELECT * FROM signature_corrections WHERE sender_domain = 'gmail.com' AND field = 'company_name'"
        )
        row = cur.fetchone()
    require(row is None, f"A freemail domain must never get a row in signature_corrections: {row}")

    contact: dict = {}
    applied = apply_learned_signature_patterns(contact, "gmail.com")
    require(applied == [], f"Nothing must be applied for a freemail domain, got {applied}")
    require(contact == {}, f"contact must be left untouched for a freemail domain, got {contact}")


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

    test_edit_signature_field_persists_and_is_tracked()
    print("PASS: correcting a detected signature field persists and is tracked as human_edited")

    test_edit_signature_field_ignores_fields_the_parser_never_detected()
    print("PASS: a signature field the parser never detected cannot be injected via a correction")

    test_signature_correction_learned_and_applied_to_next_email_from_same_domain()
    print("PASS: a signature correction fills the same gap automatically for the next email from that domain")

    test_signature_learning_never_overrides_a_field_the_parser_did_detect()
    print("PASS: a learned signature pattern never overrides a value the parser actually detected")

    test_signature_learning_never_records_or_applies_a_freemail_domain()
    print("PASS: signature pattern learning never records or applies patterns for a shared freemail domain")

    test_accuracy_summary_reflects_a_correction()
    print("PASS: accuracy summary separates 'filled a gap' from 'fixed a wrong value'")

    test_accuracy_summary_flags_small_samples_as_unreliable()
    print("PASS: small-sample fields are flagged unreliable rather than shown as a confident percentage")

    print("HERMES-950 review editing + accuracy check PASSED")


if __name__ == "__main__":
    main()
