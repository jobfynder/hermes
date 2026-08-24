from datetime import UTC, datetime, timedelta

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.claim.service import (
    _save_claim,
    confirm_claim,
    get_claim,
    get_claim_by_token,
    prepare_claim,
)
from app.drafts.service import get_draft_object
from app.email_parsing.provenance import load_field_provenance


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


FORWARDED_REQUIREMENT_BODY = """---------- Forwarded message ---------
From: Chandan Kumar <chandan.kumar@scalable-systems.com>
Date: Mon, Aug 24, 2026 at 9:36 AM
Subject: CITRIX NETWORK ADMINISTRATOR - Burlington, MA
To: nvoids@benchteq.com

Job Title: Citrix Network Administrator
Required Skills: Citrix, Active Directory, Network Administration
Location: Burlington, MA
Rate: $65/hr
"""


def test_full_claim_and_verify_round_trip() -> None:
    intake = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="claim-source-forwarded-1",
            content_type="text",
            text=FORWARDED_REQUIREMENT_BODY,
        )
    )
    draft_id = intake.understanding_result["draft_id"]
    draft = get_draft_object(draft_id)

    require(draft.draft_type == "draft_job_requirement", "Expected a job-requirement draft")
    require(
        draft.metadata.get("original_sender_candidate", {}).get("email")
        == "chandan.kumar@scalable-systems.com",
        "Forwarded sender must have been resolved onto the draft (spec 4.1)",
    )

    prepared = prepare_claim(draft_id)
    require(prepared.status == "prepared", f"Expected prepared, got {prepared.status}: {prepared.errors}")
    require(prepared.claim.recruiter_email == "chandan.kumar@scalable-systems.com", "Wrong recruiter resolved")
    require(prepared.claim.status == "PENDING_CLAIM", "New claim must start PENDING_CLAIM")
    require(prepared.claim.resolution_method == "forwarded_header", "Expected forwarded_header resolution")
    require("Citrix Network Administrator" in (prepared.email_subject or ""), "Subject must include the job title")
    require(f"/claim/{prepared.claim.token}" in prepared.email_body, "Body must include the claim link")

    # Preparing twice for the same draft must not create a second claim.
    prepared_again = prepare_claim(draft_id)
    require(prepared_again.status == "already_prepared", "Re-preparing must return the existing claim")
    require(prepared_again.claim.claim_id == prepared.claim.claim_id, "Must be the same claim")

    fetched = get_claim_by_token(prepared.claim.token)
    require(fetched is not None, "Claim must be fetchable by its token")
    require(fetched.prefilled_fields.get("location") == "Burlington, MA", "Prefilled location mismatch")

    confirmed = confirm_claim(
        prepared.claim.token,
        corrections={"location": "Burlington, MA (Hybrid)", "rate_or_salary": "$68/hr"},
    )
    require(confirmed.status == "claimed", "Confirm must succeed")
    require(confirmed.claim.status == "PUBLISHED", "Confirming must publish the record")
    require(confirmed.claim.claimed_at is not None, "claimed_at must be set")
    require(confirmed.claim.published_at is not None, "published_at must be set")
    require(
        confirmed.correction_diff.get("location") == {"before": "Burlington, MA", "after": "Burlington, MA (Hybrid)"},
        "correction_diff must capture the location change",
    )
    require("rate_or_salary" in confirmed.correction_diff, "correction_diff must capture the rate change")

    published_draft = get_draft_object(draft_id)
    require(published_draft.status == "published", "Underlying draft must be marked published")
    require(
        published_draft.metadata.get("claimed_fields", {}).get("location") == "Burlington, MA (Hybrid)",
        "Published draft must carry the recruiter's corrected fields",
    )

    provenance_rows = load_field_provenance(draft_id)
    correction_rows = [row for row in provenance_rows if row["extractor"] == "recruiter_correction"]
    require(
        any(row["field_path"] == "job.location" for row in correction_rows),
        "Correction must be recorded as recruiter_correction provenance -- this is the claim loop's whole point",
    )

    # Re-confirming (double click) must be idempotent, not reprocess.
    reconfirmed = confirm_claim(prepared.claim.token, corrections={"location": "something else entirely"})
    require(reconfirmed.status == "claimed", "Idempotent re-confirm must still report claimed")
    require(
        reconfirmed.claim.prefilled_fields.get("location") != "something else entirely"
        or reconfirmed.correction_diff == confirmed.correction_diff,
        "Re-confirming an already-published claim must not silently reprocess new corrections",
    )


def test_claim_blocked_when_no_recruiter_contact_resolves() -> None:
    intake = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="claim-source-unresolved-1",
            content_type="text",
            text="Job Title: Data Engineer\nRequired Skills: Python, Spark\nLocation: Remote\n",
        )
    )
    draft_id = intake.understanding_result["draft_id"]

    result = prepare_claim(draft_id)
    require(result.status == "blocked", "Must not prepare a claim with no resolvable recruiter contact")
    require("no_recruiter_contact_resolved" in result.errors, "Wrong error reason")
    require(result.claim is None, "No claim record must be created when nothing resolves -- spec 4.1 step 4")


def test_claim_blocked_for_non_job_requirement_drafts() -> None:
    intake = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="claim-source-hotlist-1",
            content_type="text",
            sender=ChannelSender(email="vendor@staffingco.com"),
            text="Name | Title | Skills | Experience | Location\nJohn Doe | Java Dev | Java, AWS | 5 years | NYC\n",
        )
    )
    draft_id = intake.understanding_result["draft_id"]

    result = prepare_claim(draft_id)
    require(result.status == "blocked", "Hotlists must not go through the job-requirement claim flow")
    require("not_eligible_for_claim" in result.errors, "Wrong error reason")


def test_expired_claim_cannot_be_confirmed() -> None:
    intake = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="claim-source-expiry-1",
            content_type="text",
            sender=ChannelSender(email="recruiter@staffingco.com"),
            text="Job Title: QA Engineer\nRequired Skills: Selenium, Java\nLocation: Chicago, IL\n",
        )
    )
    draft_id = intake.understanding_result["draft_id"]
    prepared = prepare_claim(draft_id)
    require(prepared.status == "prepared", "Setup: claim must prepare successfully")

    claim = get_claim(prepared.claim.claim_id)
    claim.expires_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _save_claim(claim)

    result = confirm_claim(prepared.claim.token, corrections={})
    require(result.status == "blocked", "Expired claim must not be confirmable")
    require("claim_expired" in result.errors, "Wrong error reason")
    require(get_claim(claim.claim_id).status == "EXPIRED", "Claim status must flip to EXPIRED")


if __name__ == "__main__":
    test_full_claim_and_verify_round_trip()
    test_claim_blocked_when_no_recruiter_contact_resolves()
    test_claim_blocked_for_non_job_requirement_drafts()
    test_expired_claim_cannot_be_confirmed()
    print("hermes-850-claim-check: all checks passed")
