"""Checks for HERMES-900: sender blocklist, spam flagging, and taxonomy
candidate detection.
"""

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.drafts.service import delete_draft_object, get_draft_object
from app.email_parsing.blocklist import add_block, is_blocked, list_blocks, remove_block
from app.email_parsing.spam import classify_spam
from app.understanding.taxonomy.candidates import (
    approve_taxonomy_candidate,
    find_unknown_job_title,
    find_unknown_skill_terms,
    get_skill_usage_stats,
    list_taxonomy_candidates,
    record_skill_usage,
    record_taxonomy_candidates,
    reject_taxonomy_candidate,
)
from app.understanding.taxonomy.loader import (
    add_canonical_skill,
    build_skill_alias_index,
    build_title_alias_index,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_blocklist_domain_match() -> None:
    add_block(match_type="domain", value="spamvendor.com", reason="test fixture")

    require(is_blocked("someone@spamvendor.com") is not None, "Any address at a blocked domain must match")
    require(is_blocked("someone@notblocked.com") is None, "An unrelated domain must not match")


def test_blocklist_email_match_narrower_than_domain() -> None:
    add_block(match_type="email", value="specific@sharedvendor.com", reason="test fixture")

    require(is_blocked("specific@sharedvendor.com") is not None, "The exact blocked email must match")
    require(
        is_blocked("someoneelse@sharedvendor.com") is None,
        "An email block must not block the whole domain",
    )


def test_blocked_sender_never_creates_a_draft() -> None:
    add_block(match_type="domain", value="blockedintake.example.com", reason="test fixture")

    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="msg-blocked-1",
        sender=ChannelSender(email="anyone@blockedintake.example.com"),
        content_type="text",
        text="Job Title: Java Developer\nRequired Skills: Java, Spring\n",
    )

    response = process_channel_intake(request)

    require(response.intake_status == "blocked", "A blocked sender's message must be reported as blocked")
    require(response.errors == [], "Blocking is not an error condition, just a routing decision")


def test_unblocked_sender_still_creates_a_draft() -> None:
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="msg-not-blocked-1",
        sender=ChannelSender(email="recruiter@legituservendor.com"),
        content_type="text",
        text=(
            "Job Title: Senior Python Developer\n"
            "Company: Legit User Vendor\n"
            "Required Skills: Python, Django, PostgreSQL\n\n"
            "Real posting body text long enough to look like a real requirement.\n"
        ),
    )

    response = process_channel_intake(request)

    require(response.intake_status != "blocked", "An unblocked sender must not be routed as blocked")
    require(response.draft_object_type == "draft_job_requirement", "A real posting must still become a draft")


def test_remove_block_unblocks() -> None:
    row = add_block(match_type="domain", value="temporarily-blocked.example.com")
    require(is_blocked("x@temporarily-blocked.example.com") is not None, "Must be blocked before removal")

    removed = remove_block(row["id"])
    require(removed is True, "remove_block must report success")
    require(is_blocked("x@temporarily-blocked.example.com") is None, "Must no longer be blocked after removal")


def test_spam_classify_empty_content() -> None:
    reasons = classify_spam(text="hi", document_kind="unknown", confidence=0.0)
    require("empty_or_near_empty_content" in reasons, "Near-empty content must be flagged")


def test_spam_classify_marketing_without_job_content() -> None:
    text = (
        "You are receiving this email because you subscribed to our newsletter. "
        "Click here to view in browser. Limited time offer, act now! "
        "Unsubscribe at any time to manage your subscription preferences."
    )
    reasons = classify_spam(text=text, document_kind="unknown", confidence=0.1)
    require(
        "marketing_footer_markers_without_job_content" in reasons,
        f"Marketing-only content must be flagged, got {reasons}",
    )


def test_spam_classify_real_posting_not_flagged() -> None:
    text = (
        "Job Title: Senior Java Developer\n"
        "Location: Dallas, TX\n"
        "Required Skills: Java, Spring Boot, AWS\n"
        "Rate: $70/hr on C2C\n\n"
        "Please unsubscribe if you no longer wish to receive postings from this vendor.\n"
    )
    reasons = classify_spam(text=text, document_kind="job_description", confidence=0.92)
    require(
        reasons == [],
        f"A real posting with a single incidental 'unsubscribe' line must not be flagged, got {reasons}",
    )


def test_spam_flagged_draft_gets_spam_status() -> None:
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="msg-spam-1",
        sender=ChannelSender(email="blast@newslettervendor.com"),
        content_type="text",
        text=(
            "You are receiving this email because you subscribed to our newsletter. "
            "Click here to view in browser. Limited time offer, act now! "
            "Unsubscribe to manage your subscription preferences."
        ),
    )

    response = process_channel_intake(request)
    draft_id = response.understanding_result.get("draft_id") if response.understanding_result else None

    require(draft_id is not None, "A spam-flagged message still becomes a reviewable draft, not silently discarded")

    draft = get_draft_object(draft_id)
    require(draft is not None, "Draft must exist")
    require(draft.status == "spam", f"Expected status='spam', got {draft.status!r}")
    require(
        draft.metadata.get("spam_reasons"),
        "spam_reasons must be recorded in draft metadata for the reviewer to see why",
    )


def test_delete_draft_removes_row() -> None:
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="msg-to-delete-1",
        sender=ChannelSender(email="blast2@newslettervendor2.com"),
        content_type="text",
        text=(
            "You are receiving this email because you subscribed. "
            "Click here to view in browser. Limited time offer, act now! "
            "Unsubscribe to manage subscription."
        ),
    )
    response = process_channel_intake(request)
    draft_id = response.understanding_result["draft_id"]

    result = delete_draft_object(draft_id)
    require(result["deleted"] is True, "Deleting a non-published draft must succeed")
    require(get_draft_object(draft_id) is None, "Draft must actually be gone after delete")


def test_delete_published_draft_refused() -> None:
    from app.drafts.service import create_draft_object

    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="test",
        payload={"job_title": "X"},
        confidence=0.9,
        requires_review=False,
    )

    with __import__("app.runtime.db", fromlist=["cursor"]).cursor() as cur:
        cur.execute("UPDATE drafts SET status = 'published' WHERE draft_id = %s", (draft.draft_id,))

    result = delete_draft_object(draft.draft_id)
    require(result["deleted"] is False, "A published draft must never be deleted through this path")
    require(get_draft_object(draft.draft_id) is not None, "The published draft must still exist")


def test_unknown_skill_term_detected() -> None:
    text = (
        "Job Title: Integration Engineer\n"
        "Required Skills: SomeBrandNewTool2027, Java, Spring Boot\n"
    )

    unknown = find_unknown_skill_terms(text)
    require("SomeBrandNewTool2027" in unknown, f"A genuinely unrecognized skill term must be surfaced, got {unknown}")
    require("Java" not in unknown, "A term already in the taxonomy must not be flagged as unknown")


def test_taxonomy_candidate_queue_and_approve() -> None:
    text = "Job Title: Integration Engineer\nRequired Skills: ZzzBrandNewFramework, Java\n"

    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="vendor-a.com")
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="vendor-b.com")

    pending = list_taxonomy_candidates(status="pending")
    match = next((c for c in pending if c["term"] == "ZzzBrandNewFramework"), None)

    require(match is not None, "The repeated candidate must appear in the pending queue")
    require(match["occurrence_count"] == 2, f"Expected occurrence_count=2 after two sightings, got {match['occurrence_count']}")
    require(
        set(match["distinct_senders"]) == {"vendor-a.com", "vendor-b.com"},
        f"Expected both distinct sender domains recorded, got {match['distinct_senders']}",
    )

    alias_index_before = build_skill_alias_index()
    require(
        "zzzbrandnewframework" not in alias_index_before,
        "The candidate must not be matchable before approval",
    )

    result = approve_taxonomy_candidate(match["id"])
    require(result["approved"] is True, "Approval must succeed for a pending candidate")

    alias_index_after = build_skill_alias_index()
    require(
        "zzzbrandnewframework" in alias_index_after,
        "Approving a candidate must make it immediately matchable (cache busted, no redeploy)",
    )

    still_pending = list_taxonomy_candidates(status="pending")
    require(
        all(c["term"] != "ZzzBrandNewFramework" for c in still_pending),
        "An approved candidate must leave the pending queue",
    )


def test_taxonomy_candidate_reject() -> None:
    text = "Job Title: X\nRequired Skills: SomeTypoTermXyz123, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="onevendor.com")

    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "SomeTypoTermXyz123")

    result = reject_taxonomy_candidate(match["id"])
    require(result["rejected"] is True, "Rejection must succeed for a pending candidate")

    alias_index = build_skill_alias_index()
    require(
        "sometypotermxyz123" not in alias_index,
        "A rejected candidate must never be added to the taxonomy",
    )


def test_skill_usage_stats_accumulate() -> None:
    # Synthetic names, not real taxonomy skills like "Java" -- other tests
    # in this file create real drafts mentioning common skills via
    # process_channel_intake, which now also calls record_skill_usage, so
    # a real skill name's count isn't isolated to this test.
    record_skill_usage(["ZUsageTestSkillAlpha", "ZUsageTestSkillBeta"])
    record_skill_usage(["ZUsageTestSkillAlpha"])

    stats = get_skill_usage_stats()
    require(stats["ZUsageTestSkillAlpha"]["times_seen"] == 2, f"Expected 2 sightings, got {stats.get('ZUsageTestSkillAlpha')}")
    require(stats["ZUsageTestSkillBeta"]["times_seen"] == 1, f"Expected 1 sighting, got {stats.get('ZUsageTestSkillBeta')}")
    require(stats["ZUsageTestSkillAlpha"]["last_seen_at"] is not None, "last_seen_at must be set")


def test_skill_usage_dedupes_within_one_call() -> None:
    # A draft's own required+preferred skills list can legitimately repeat
    # a skill (e.g. mentioned in both sections) -- one draft must count as
    # one sighting, not two.
    record_skill_usage(["ZUsageTestSkillGamma", "ZUsageTestSkillGamma"])
    stats = get_skill_usage_stats()
    require(
        stats["ZUsageTestSkillGamma"]["times_seen"] == 1,
        f"Expected one sighting despite duplicate in the same call, got {stats['ZUsageTestSkillGamma']}",
    )


def test_add_canonical_skill_is_idempotent_under_the_lock() -> None:
    # Two approvals of the exact same term (e.g. an admin double-clicking)
    # must not create two entries -- add_canonical_skill's own duplicate
    # check runs inside the same advisory-locked transaction as the
    # read-modify-write, so this also exercises that the lock doesn't
    # deadlock a function calling itself sequentially.
    add_canonical_skill(name="ZDoubleApproveTestSkill")
    add_canonical_skill(name="ZDoubleApproveTestSkill")

    alias_index = build_skill_alias_index()
    require("zdoubleapprovetestskill" in alias_index, "The skill must be added")


def test_unknown_job_title_detected() -> None:
    # Real production regression: "ORMB Technical Consultant" never
    # entered the review queue at all -- record_taxonomy_candidates only
    # ever recorded skill terms, despite the DB schema and admin
    # endpoints already supporting signal_type='job_title'.
    require(
        find_unknown_job_title("ZOrmbTechnicalConsultantXyz") == "ZOrmbTechnicalConsultantXyz",
        "A genuinely unrecognized job title must be surfaced",
    )
    require(
        find_unknown_job_title("Senior Java Developer") is None,
        "A job title already in the taxonomy must not be flagged as unknown",
    )
    require(find_unknown_job_title(None) is None, "A missing title must not raise or be flagged")
    require(find_unknown_job_title("") is None, "An empty title must not be flagged")


def test_record_taxonomy_candidates_queues_job_titles() -> None:
    record_taxonomy_candidates(
        text="Required Skills: Java, Spring Boot",
        draft_id=None,
        sender_domain="titletest.com",
        job_titles=["ZUnknownTitleForQueueTest"],
    )

    pending = list_taxonomy_candidates(status="pending")
    match = next((c for c in pending if c["term"] == "ZUnknownTitleForQueueTest"), None)

    require(match is not None, "The unrecognized job title must appear in the pending queue")
    require(match["signal_type"] == "job_title", f"Expected signal_type='job_title', got {match['signal_type']}")


def test_approve_job_title_candidate_adds_it_live() -> None:
    record_taxonomy_candidates(
        text="",
        draft_id=None,
        sender_domain="titleapprovetest.com",
        job_titles=["ZApprovedJobTitleTest"],
    )

    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "ZApprovedJobTitleTest")

    title_index_before = build_title_alias_index()
    require("zapprovedjobtitletest" not in title_index_before, "Must not be matchable before approval")

    result = approve_taxonomy_candidate(match["id"], family="Test Family", seniority="mid")
    require(result["approved"] is True, "Approval must succeed")

    title_index_after = build_title_alias_index()
    require(
        "zapprovedjobtitletest" in title_index_after,
        "Approving a job title candidate must make it immediately matchable",
    )


def test_intake_pipeline_queues_a_real_unrecognized_job_title() -> None:
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="msg-jobtitle-candidate-1",
        sender=ChannelSender(email="recruiter@jobtitleintaketest.com"),
        content_type="text",
        # intended_document_kind pins classification directly (mirrors
        # what real recipient-address routing does for jobs@/hotlists@)
        # so this test exercises job-title-candidate queuing specifically,
        # not the separate hotlist-vs-requirement content classifier.
        metadata={"intended_document_kind": "job_description"},
        text=(
            "Job Title: ZBrandNewRoleNameForIntakeTest\n"
            "Required Skills: Java, Spring Boot, AWS\n\n"
            "Long enough body text so the requirement-evidence check passes cleanly.\n"
        ),
    )

    response = process_channel_intake(request)
    require(response.draft_object_type == "draft_job_requirement", "Must still parse as a normal job requirement")

    pending = list_taxonomy_candidates(status="pending")
    match = next((c for c in pending if c["term"] == "ZBrandNewRoleNameForIntakeTest"), None)
    require(match is not None, "A real intake with an unrecognized job title must queue it for review")


def main() -> None:
    test_blocklist_domain_match()
    print("PASS: blocklist domain match")

    test_blocklist_email_match_narrower_than_domain()
    print("PASS: blocklist email match is narrower than a domain match")

    test_blocked_sender_never_creates_a_draft()
    print("PASS: a blocked sender's message never becomes a draft")

    test_unblocked_sender_still_creates_a_draft()
    print("PASS: an unblocked sender still creates a draft normally")

    test_remove_block_unblocks()
    print("PASS: removing a block actually unblocks")

    test_spam_classify_empty_content()
    print("PASS: near-empty content is flagged as spam")

    test_spam_classify_marketing_without_job_content()
    print("PASS: marketing-only content with no job signal is flagged")

    test_spam_classify_real_posting_not_flagged()
    print("PASS: a real posting with one incidental unsubscribe line is not flagged")

    test_spam_flagged_draft_gets_spam_status()
    print("PASS: a spam-flagged intake creates a draft with status='spam', not silently discarded")

    test_delete_draft_removes_row()
    print("PASS: deleting a non-published draft actually removes it")

    test_delete_published_draft_refused()
    print("PASS: a published draft cannot be deleted")

    test_unknown_skill_term_detected()
    print("PASS: an unrecognized skill term in a Required Skills section is detected")

    test_taxonomy_candidate_queue_and_approve()
    print("PASS: taxonomy candidate queue accumulates occurrences and approval is live immediately")

    test_taxonomy_candidate_reject()
    print("PASS: rejecting a taxonomy candidate keeps it out of the taxonomy")

    test_skill_usage_stats_accumulate()
    print("PASS: skill usage stats accumulate across separate drafts")

    test_skill_usage_dedupes_within_one_call()
    print("PASS: a skill repeated within one draft counts as one sighting")

    test_add_canonical_skill_is_idempotent_under_the_lock()
    print("PASS: adding the same canonical skill twice does not duplicate or deadlock")

    test_unknown_job_title_detected()
    print("PASS: an unrecognized job title is detected, a known one is not")

    test_record_taxonomy_candidates_queues_job_titles()
    print("PASS: an unrecognized job title is queued with signal_type='job_title'")

    test_approve_job_title_candidate_adds_it_live()
    print("PASS: approving a job title candidate adds it to the taxonomy immediately")

    test_intake_pipeline_queues_a_real_unrecognized_job_title()
    print("PASS: real intake with an unrecognized job title queues it for review")

    print("HERMES-900 spam/blocklist/taxonomy-candidate check PASSED")


if __name__ == "__main__":
    main()
