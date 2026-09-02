"""Checks for HERMES-900: sender blocklist, spam flagging, and taxonomy
candidate detection.
"""

import json
import os

from fastapi.testclient import TestClient

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import process_channel_intake
from app.drafts.service import delete_draft_object, get_draft_object
from app.email_parsing.blocklist import add_block, is_blocked, list_blocks, remove_block
from app.email_parsing.spam import classify_spam
from app.runtime.db import cursor
from app.understanding.taxonomy.candidates import (
    approve_taxonomy_candidate,
    auto_classify_unclassified_job_titles,
    bulk_approve_taxonomy_candidates,
    bulk_reject_taxonomy_candidates,
    edit_taxonomy_candidate,
    find_unknown_job_title,
    find_unknown_skill_terms,
    get_approved_boilerplate_lines,
    get_skill_usage_stats,
    list_taxonomy_candidates,
    record_boilerplate_line_candidates,
    record_skill_usage,
    record_taxonomy_candidates,
    reject_taxonomy_candidate,
    suggest_job_title_family,
    update_skill_description,
)
from app.understanding.taxonomy.title_family_classifier import (
    classify_family_deterministically,
    classify_job_title_family,
    compute_related_job_titles,
)
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import (
    TAXONOMY_DIR,
    SkillDescriptionLocked,
    _TAXONOMY_RUNTIME_DIR,
    _loose_key,
    _writable_taxonomy_path,
    add_canonical_job_title,
    add_canonical_skill,
    bulk_backfill_related_titles,
    bulk_delete_job_titles,
    bulk_delete_skills,
    bulk_set_job_title_family,
    bulk_set_skill_category,
    build_loose_skill_key_index,
    build_loose_title_key_index,
    build_skill_alias_index,
    build_title_alias_index,
    delete_canonical_job_title,
    delete_canonical_skill,
    get_canonical_skill_entries,
    get_job_title_entries,
    set_skill_description,
    update_canonical_job_title,
    update_canonical_skill,
)
from app.main import app

client = TestClient(app)


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


def test_plain_english_stopwords_are_never_queued_as_skill_candidates() -> None:
    # Real incident: 37 plain English words -- "on", "The", "no", "must",
    # "rate", "location", "team", "core", "Able" among them -- got queued
    # as taxonomy candidates (a comma/newline split running into ordinary
    # prose) and were eventually approved as canonical "skills", each
    # with an LLM-generated description that was itself visibly
    # hallucinated. Cleaned up after the fact; this guards against it
    # recurring.
    text = (
        "Job Title: Integration Engineer\n"
        "Required Skills: SomeBrandNewTool2027, on, The, no, must, rate, location, team, Java\n"
    )

    unknown = find_unknown_skill_terms(text)
    for stopword in ("on", "The", "no", "must", "rate", "location", "team"):
        require(stopword not in unknown, f"A plain English stopword must never be queued as a skill candidate: {unknown}")
    require("SomeBrandNewTool2027" in unknown, f"A genuine new term must still be surfaced: {unknown}")


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


def test_edit_taxonomy_candidate_corrects_a_parser_artifact() -> None:
    # "!!" survives extraction (not one of the characters the parser
    # strips), a realistic stand-in for stray formatting/OCR noise that
    # leaks into a term -- something a reviewer should fix before it
    # becomes a permanent, wrong entry in the canonical taxonomy.
    text = "Job Title: X\nRequired Skills: ZzzCloudTool!!, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="edittest.com")

    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "ZzzCloudTool!!")

    result = edit_taxonomy_candidate(match["id"], "ZzzCloudTool")
    require(result["edited"] is True, "Editing a pending candidate's term must succeed")
    require(result["term"] == "ZzzCloudTool", f"Expected the corrected term back, got {result['term']}")

    pending_after = list_taxonomy_candidates(status="pending")
    updated = next(c for c in pending_after if c["id"] == match["id"])
    require(updated["term"] == "ZzzCloudTool", "The stored term must reflect the edit")
    require(
        updated["normalized_term"] == "zzzcloudtool",
        f"normalized_term must be recomputed from the edited term, got {updated['normalized_term']}",
    )

    approved = approve_taxonomy_candidate(match["id"])
    require(
        approved["term"] == "ZzzCloudTool", "Approval after an edit must use the corrected term, not the original"
    )


def test_edit_taxonomy_candidate_rejects_empty_term() -> None:
    text = "Job Title: X\nRequired Skills: SomeEditGuardTerm, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="editguard.com")

    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "SomeEditGuardTerm")

    result = edit_taxonomy_candidate(match["id"], "   ")
    require(result["edited"] is False, "An empty/whitespace-only term must be refused")


def test_edit_taxonomy_candidate_only_touches_pending_rows() -> None:
    text = "Job Title: X\nRequired Skills: AlreadyReviewedTermXyz, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="reviewed.com")

    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "AlreadyReviewedTermXyz")
    reject_taxonomy_candidate(match["id"])

    result = edit_taxonomy_candidate(match["id"], "SomethingElse")
    require(result["edited"] is False, "A candidate that is already reviewed (rejected/approved) must not be editable")


def test_deterministic_glossary_is_used_before_the_llm() -> None:
    description = generate_skill_description("AWS", category="Tool/Technology")
    require(
        description == "Amazon's cloud platform for hosting apps, storage, and databases online instead of on physical servers.",
        f"A glossary term must return the curated deterministic description, got {description!r}",
    )

    description_case_insensitive = generate_skill_description("aws")
    require(
        description_case_insensitive == description,
        "Deterministic lookup must be case/formatting-insensitive, same as taxonomy key normalization",
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


def test_bulk_approve_taxonomy_candidates() -> None:
    text = "Job Title: X\nRequired Skills: ZzzBulkApproveOne, ZzzBulkApproveTwo, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="bulkapprove.com")

    pending = list_taxonomy_candidates(status="pending")
    ids = [c["id"] for c in pending if c["term"] in {"ZzzBulkApproveOne", "ZzzBulkApproveTwo"}]
    require(len(ids) == 2, f"Expected both candidates queued, got {pending}")

    result = bulk_approve_taxonomy_candidates(ids)
    require(result["approved_count"] == 2, f"Expected both approved, got {result}")
    require(result["failed"] == [], f"Expected no failures, got {result['failed']}")

    alias_index = build_skill_alias_index()
    require("zzzbulkapproveone" in alias_index, "First candidate must be live in the taxonomy immediately")
    require("zzzbulkapprovetwo" in alias_index, "Second candidate must be live in the taxonomy immediately")

    still_pending = list_taxonomy_candidates(status="pending")
    require(
        all(c["id"] not in ids for c in still_pending),
        "Bulk-approved candidates must leave the pending queue",
    )


def test_bulk_reject_taxonomy_candidates() -> None:
    text = "Job Title: X\nRequired Skills: ZzzBulkRejectOne, ZzzBulkRejectTwo, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="bulkreject.com")

    pending = list_taxonomy_candidates(status="pending")
    ids = [c["id"] for c in pending if c["term"] in {"ZzzBulkRejectOne", "ZzzBulkRejectTwo"}]

    result = bulk_reject_taxonomy_candidates(ids)
    require(result["rejected_count"] == 2, f"Expected both rejected, got {result}")

    alias_index = build_skill_alias_index()
    require("zzzbulkrejectone" not in alias_index, "A bulk-rejected candidate must never enter the taxonomy")
    require("zzzbulkrejecttwo" not in alias_index, "A bulk-rejected candidate must never enter the taxonomy")


def test_bulk_approve_reports_partial_failure_without_stopping() -> None:
    text = "Job Title: X\nRequired Skills: ZzzBulkPartialOne, Java\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="bulkpartial.com")

    pending = list_taxonomy_candidates(status="pending")
    real_id = next(c["id"] for c in pending if c["term"] == "ZzzBulkPartialOne")
    already_reviewed_id = 999999999  # doesn't exist -- stands in for "someone else already reviewed it"

    result = bulk_approve_taxonomy_candidates([real_id, already_reviewed_id])
    require(result["approved_count"] == 1, f"The valid candidate must still be approved: {result}")
    require(len(result["failed"]) == 1, f"The bad id must be reported as a failure, not raise: {result}")
    require(
        result["failed"][0]["candidate_id"] == already_reviewed_id,
        f"The failure must identify which id it was: {result['failed']}",
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


def test_update_canonical_job_title_renames_and_keeps_old_wording_as_alias() -> None:
    add_canonical_job_title(title="ZTitleEditRenameSource")

    result = update_canonical_job_title(
        "ZTitleEditRenameSource", new_title="ZTitleEditRenameTarget", family="Data", seniority="senior"
    )
    require(result["updated"] is True, f"Rename must succeed: {result}")
    require(result["title"] == "ZTitleEditRenameTarget", f"Wrong title in result: {result}")

    index = build_title_alias_index()
    require(
        "ztitleeditrenamesource" in index,
        "The OLD title text must still be recognized, as an alias -- a posting using the old wording must not "
        "suddenly look like a new unknown term again",
    )
    require("ztitleeditrenametarget" in index, "The NEW title must be recognized")
    require(
        index["ztitleeditrenamesource"] == "ZTitleEditRenameTarget",
        f"The old wording must resolve to the new canonical title: {index['ztitleeditrenamesource']}",
    )


def test_update_canonical_job_title_refuses_a_collision() -> None:
    add_canonical_job_title(title="ZTitleEditCollisionA")
    add_canonical_job_title(title="ZTitleEditCollisionB")

    result = update_canonical_job_title("ZTitleEditCollisionA", new_title="ZTitleEditCollisionB")
    require(result["updated"] is False, f"A rename that collides with a DIFFERENT existing title must be refused: {result}")
    require(result["reason"] == "duplicate_title", f"Wrong reason: {result}")

    index = build_title_alias_index()
    require(
        "ztitleeditcollisiona" in index,
        "A refused rename must leave the original title untouched, not half-applied",
    )


def test_update_canonical_job_title_family_and_seniority_only() -> None:
    add_canonical_job_title(title="ZTitleEditReclassifyOnly")

    result = update_canonical_job_title("ZTitleEditReclassifyOnly", family="Project Management", seniority="lead")
    require(result["updated"] is True, f"Reclassifying without a rename must succeed: {result}")

    entry = next(e for e in get_job_title_entries() if e["title"] == "ZTitleEditReclassifyOnly")
    require(entry["family"] == "Project Management", f"Wrong family: {entry}")
    require(entry["seniority"] == "lead", f"Wrong seniority: {entry}")


def test_update_canonical_job_title_not_found() -> None:
    result = update_canonical_job_title("ZThisJobTitleWasNeverAdded", family="Data")
    require(result["updated"] is False, f"Editing a title that doesn't exist must fail cleanly: {result}")
    require(result["reason"] == "job_title_not_found", f"Wrong reason: {result}")


def test_bulk_set_job_title_family() -> None:
    add_canonical_job_title(title="ZBulkFamilyTestOne")
    add_canonical_job_title(title="ZBulkFamilyTestTwo")

    result = bulk_set_job_title_family(["ZBulkFamilyTestOne", "ZBulkFamilyTestTwo"], "Sales")
    require(result["updated_count"] == 2, f"Both titles must be updated in one call: {result}")

    entries = {e["title"]: e for e in get_job_title_entries()}
    require(entries["ZBulkFamilyTestOne"]["family"] == "Sales", f"Wrong family: {entries['ZBulkFamilyTestOne']}")
    require(entries["ZBulkFamilyTestTwo"]["family"] == "Sales", f"Wrong family: {entries['ZBulkFamilyTestTwo']}")


def test_delete_canonical_job_title_removes_it_without_leaving_an_alias() -> None:
    add_canonical_job_title(title="ZTitleDeleteTarget")
    require(
        "ztitledeletetarget" in build_title_alias_index(), "Sanity check: the title must exist before deleting it"
    )

    result = delete_canonical_job_title("ZTitleDeleteTarget")
    require(result["deleted"] is True, f"Delete must succeed: {result}")

    index = build_title_alias_index()
    require(
        "ztitledeletetarget" not in index,
        "A deleted title must not resolve to anything -- unlike a rename, delete keeps no alias",
    )


def test_delete_canonical_job_title_not_found() -> None:
    result = delete_canonical_job_title("ZThisJobTitleWasNeverAdded")
    require(result["deleted"] is False, f"Deleting a title that doesn't exist must fail cleanly: {result}")
    require(result["reason"] == "job_title_not_found", f"Wrong reason: {result}")


def test_bulk_delete_job_titles() -> None:
    add_canonical_job_title(title="ZBulkDeleteTitleOne")
    add_canonical_job_title(title="ZBulkDeleteTitleTwo")

    result = bulk_delete_job_titles(["ZBulkDeleteTitleOne", "ZBulkDeleteTitleTwo"])
    require(result["deleted_count"] == 2, f"Both titles must be deleted in one call: {result}")

    index = build_title_alias_index()
    require("zbulkdeletetitleone" not in index, "First title must be gone")
    require("zbulkdeletetitletwo" not in index, "Second title must be gone")


def test_update_canonical_job_title_applies_a_case_only_rename() -> None:
    # Regression test: a rename that only fixes casing/whitespace has the
    # SAME normalized key as before ("zcasingonlyrename developer"
    # either way), so the old code's `if new_key != current_key` guard
    # skipped writing the corrected text entirely while still reporting
    # updated=True -- a reviewer's "fix the casing" edit silently did
    # nothing and the row reverted to the old text on reload.
    add_canonical_job_title(title="zcasingonlyrename developer")

    result = update_canonical_job_title("zcasingonlyrename developer", new_title="ZCasingOnlyRename Developer")
    require(result["updated"] is True, f"Rename must succeed: {result}")
    require(
        result["title"] == "ZCasingOnlyRename Developer",
        f"The corrected casing must actually be written, not silently dropped: {result}",
    )

    entry = next(e for e in get_job_title_entries() if e["title"] == "ZCasingOnlyRename Developer")
    require(entry is not None, "The entry must be findable under its corrected casing")


def test_update_canonical_job_title_computes_related_titles_on_rename() -> None:
    # A made-up tech token ("zqxvframework") that can't collide with any
    # real seed title -- the production taxonomy has hundreds of real
    # "Java Developer"-shaped titles that would otherwise legitimately
    # outrank this test's own fixture for the capped top-N slots.
    # related_titles is only recomputed when title or family actually
    # CHANGE -- add both fixtures under "Unclassified" (add_canonical_
    # job_title's own related_titles pass ran before the second fixture
    # existed), then reclassify the base one to a real family so the
    # update path's recompute actually triggers.
    add_canonical_job_title(title="ZRelatedTitleBase Zqxvframework Developer")
    add_canonical_job_title(title="ZRelatedTitleOther Zqxvframework Engineer")

    result = update_canonical_job_title("ZRelatedTitleBase Zqxvframework Developer", family="Software Engineering")
    require(result["updated"] is True, f"Update must succeed: {result}")

    entry = next(e for e in get_job_title_entries() if e["title"] == "ZRelatedTitleBase Zqxvframework Developer")
    require(
        "ZRelatedTitleOther Zqxvframework Engineer" in entry["related_titles"],
        f"A title sharing a real keyword ('zqxvframework') must be found as related: {entry['related_titles']}",
    )


def test_add_canonical_job_title_rejects_a_duplicate_that_is_only_an_alias() -> None:
    # The old duplicate check only compared a new title's key against
    # other entries' own `title` field, so a term already recognized
    # only as an ALIAS of a different canonical title slipped through as
    # if it were brand new -- two entries for the same real role.
    add_canonical_job_title(title="ZAliasDupBase Developer", aliases=["ZAliasDupAlias Developer"])
    before_count = len(get_job_title_entries())

    add_canonical_job_title(title="ZAliasDupAlias Developer")

    require(
        len(get_job_title_entries()) == before_count,
        "A title that's already recognized as an ALIAS of an existing title must not be added as a new entry",
    )


def test_add_canonical_job_title_rejects_a_loose_punctuation_variant() -> None:
    add_canonical_job_title(title="ZLooseDup Node.js Developer")
    before_count = len(get_job_title_entries())

    add_canonical_job_title(title="ZLooseDup NodeJS Developer")

    require(
        len(get_job_title_entries()) == before_count,
        "A punctuation-only spelling variant of an existing title must not be added as a second entry",
    )


def test_compute_related_job_titles_finds_token_overlap_matches() -> None:
    other_entries = [
        {"title": "Senior Java Engineer", "family": "Software Engineering"},
        {"title": "Python Developer", "family": "Software Engineering"},
        {"title": "Business Analyst", "family": "Business Analysis"},
    ]
    related = compute_related_job_titles("Java Developer", "Software Engineering", other_entries)
    require("Senior Java Engineer" in related, f"Shared core word 'java' must be found as related: {related}")
    require(
        "Python Developer" not in related,
        f"Sharing only the generic word 'developer' with a DIFFERENT tech must not count as related: {related}",
    )


def test_bulk_backfill_related_titles_skips_entries_that_already_have_some() -> None:
    # Two fixtures sharing a made-up core token so they're guaranteed to
    # match each other regardless of what real seed titles happen to be
    # present, and nothing else the seed data could coincidentally match.
    add_canonical_job_title(title="ZBackfillNoRelated Zqxvbackfill Developer")
    add_canonical_job_title(title="ZBackfillHasRelated Zqxvbackfill Developer")

    # Directly hand-pick a related title for the second one and write it
    # straight to the taxonomy file -- simulates a reviewer's own edit,
    # which bulk_backfill_related_titles must never overwrite.
    path = _writable_taxonomy_path("job_titles.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = next(e for e in data["titles"] if e["title"] == "ZBackfillHasRelated Zqxvbackfill Developer")
    entry["related_titles"] = ["ZHandPicked Title"]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    result = bulk_backfill_related_titles()
    require(
        "ZBackfillNoRelated Zqxvbackfill Developer" in result["backfilled_titles"],
        f"The entry with no related titles must be backfilled: {result}",
    )

    entries_after = {e["title"]: e for e in get_job_title_entries()}
    require(
        entries_after["ZBackfillHasRelated Zqxvbackfill Developer"]["related_titles"] == ["ZHandPicked Title"],
        "An entry that already had related titles must be left exactly as-is by the backfill",
    )
    require(
        "ZBackfillHasRelated Zqxvbackfill Developer" in entries_after["ZBackfillNoRelated Zqxvbackfill Developer"]["related_titles"],
        "The backfilled entry must actually find its token-overlap partner",
    )


def test_find_unknown_skill_terms_ignores_a_loose_punctuation_duplicate() -> None:
    add_canonical_skill(name="ZLooseSkillDup Node.js")

    unknown = find_unknown_skill_terms("Required Skills: ZLooseSkillDup NodeJS, Java\n")
    require(
        not any(_loose_key(term) == _loose_key("ZLooseSkillDup Node.js") for term in unknown),
        f"A punctuation-only spelling variant of a known skill must not be queued as unknown: {unknown}",
    )


def test_find_unknown_job_title_ignores_a_loose_punctuation_duplicate() -> None:
    add_canonical_job_title(title="ZLooseTitleDup Node.js Developer")

    result = find_unknown_job_title("ZLooseTitleDup NodeJS Developer")
    require(
        result is None,
        f"A punctuation-only spelling variant of a known title must not be queued as unknown: {result}",
    )


def test_find_unknown_skill_terms_filters_sentence_fragments_and_noise() -> None:
    # Real production incident: a one-time cleanup of a 3,884-item
    # candidate backlog found ~41% was confidently-rejectable junk by
    # shape alone -- fragments, verb phrases, emails, table rows, person
    # names -- none needing an LLM or a human to recognize. Promoted
    # into detection itself so it never reaches the queue again.
    text = (
        "Required Skills: ZGenuineSkillXyz, and global delivery teams, "
        "Drive business alignment, Sathish.b@sparktekusa.com, "
        "Venkat Ram, Strong customer focus, ZAnotherGenuineSkillAbc\n"
    )

    unknown = find_unknown_skill_terms(text)
    require("ZGenuineSkillXyz" in unknown, f"A genuine new term must still be surfaced: {unknown}")
    require("ZAnotherGenuineSkillAbc" in unknown, f"A genuine new term must still be surfaced: {unknown}")
    require(
        not any(
            t in unknown
            for t in (
                "and global delivery teams",
                "Drive business alignment",
                "Sathish.b@sparktekusa.com",
                "Venkat Ram",
                "Strong customer focus",
            )
        ),
        f"Sentence fragments, verb phrases, an email, and a person's name must never be queued: {unknown}",
    )


def test_find_unknown_job_title_filters_sentence_fragments_and_noise() -> None:
    require(
        find_unknown_job_title("Durga Prasad") is None,
        "A person's name must never be queued as a job title candidate",
    )
    require(
        find_unknown_job_title("22 VD DATA ANALYST 4+Y ONSITE") is None,
        "A spreadsheet table row must never be queued as a job title candidate",
    )
    require(
        find_unknown_job_title("Drive complex program delivery across teams") is None,
        "A verb-phrase sentence fragment must never be queued as a job title candidate",
    )
    require(
        find_unknown_job_title("ZGenuineTitleCandidateXyz Developer") == "ZGenuineTitleCandidateXyz Developer",
        "A genuine new title must still be surfaced",
    )


def test_update_canonical_skill_renames_and_keeps_old_wording_as_alias() -> None:
    add_canonical_skill(name="ZSkillEditRenameSource")

    result = update_canonical_skill("ZSkillEditRenameSource", new_name="ZSkillEditRenameTarget", category="Data")
    require(result["updated"] is True, f"Rename must succeed: {result}")
    require(result["name"] == "ZSkillEditRenameTarget", f"Wrong name in result: {result}")

    index = build_skill_alias_index()
    require(
        "zskilleditrenamesource" in index,
        "The OLD skill name must still be recognized, as an alias, same reasoning as job title renames",
    )
    require("zskilleditrenametarget" in index, "The NEW skill name must be recognized")
    require(
        index["zskilleditrenamesource"] == "ZSkillEditRenameTarget",
        f"The old name must resolve to the new canonical skill: {index['zskilleditrenamesource']}",
    )


def test_update_canonical_skill_refuses_a_collision() -> None:
    add_canonical_skill(name="ZSkillEditCollisionA")
    add_canonical_skill(name="ZSkillEditCollisionB")

    result = update_canonical_skill("ZSkillEditCollisionA", new_name="ZSkillEditCollisionB")
    require(result["updated"] is False, f"A rename that collides with a DIFFERENT existing skill must be refused: {result}")
    require(result["reason"] == "duplicate_skill", f"Wrong reason: {result}")


def test_update_canonical_skill_not_found() -> None:
    result = update_canonical_skill("ZThisSkillWasNeverAdded", category="Data")
    require(result["updated"] is False, f"Editing a skill that doesn't exist must fail cleanly: {result}")
    require(result["reason"] == "skill_not_found", f"Wrong reason: {result}")


def test_delete_canonical_skill_removes_it_without_leaving_an_alias() -> None:
    add_canonical_skill(name="ZSkillDeleteTarget")
    require("zskilldeletetarget" in build_skill_alias_index(), "Sanity check: the skill must exist before deleting it")

    result = delete_canonical_skill("ZSkillDeleteTarget")
    require(result["deleted"] is True, f"Delete must succeed: {result}")

    index = build_skill_alias_index()
    require(
        "zskilldeletetarget" not in index,
        "A deleted skill must not resolve to anything -- unlike a rename, delete keeps no alias",
    )


def test_bulk_delete_skills() -> None:
    add_canonical_skill(name="ZBulkDeleteSkillOne")
    add_canonical_skill(name="ZBulkDeleteSkillTwo")

    result = bulk_delete_skills(["ZBulkDeleteSkillOne", "ZBulkDeleteSkillTwo"])
    require(result["deleted_count"] == 2, f"Both skills must be deleted in one call: {result}")

    index = build_skill_alias_index()
    require("zbulkdeleteskillone" not in index, "First skill must be gone")
    require("zbulkdeleteskilltwo" not in index, "Second skill must be gone")


def test_bulk_set_skill_category() -> None:
    add_canonical_skill(name="ZBulkCategoryTestOne")
    add_canonical_skill(name="ZBulkCategoryTestTwo")

    result = bulk_set_skill_category(["ZBulkCategoryTestOne", "ZBulkCategoryTestTwo"], "Soft Skill")
    require(result["updated_count"] == 2, f"Both skills must be updated in one call: {result}")

    entries = {e["name"]: e for e in get_canonical_skill_entries()}
    require(entries["ZBulkCategoryTestOne"]["category"] == "Soft Skill", f"Wrong category: {entries['ZBulkCategoryTestOne']}")
    require(entries["ZBulkCategoryTestTwo"]["category"] == "Soft Skill", f"Wrong category: {entries['ZBulkCategoryTestTwo']}")


def test_update_canonical_skill_applies_a_case_only_rename() -> None:
    # Same regression as the job title version above.
    add_canonical_skill(name="zcasingonlyrename skill")

    result = update_canonical_skill("zcasingonlyrename skill", new_name="ZCasingOnlyRename Skill")
    require(result["updated"] is True, f"Rename must succeed: {result}")
    require(
        result["name"] == "ZCasingOnlyRename Skill",
        f"The corrected casing must actually be written, not silently dropped: {result}",
    )

    entry = next(e for e in get_canonical_skill_entries() if e["name"] == "ZCasingOnlyRename Skill")
    require(entry is not None, "The entry must be findable under its corrected casing")


def test_add_canonical_skill_rejects_a_duplicate_that_is_only_an_alias() -> None:
    add_canonical_skill(name="ZAliasDupBaseSkill", aliases=["ZAliasDupAliasSkill"])
    before_count = len(get_canonical_skill_entries())

    add_canonical_skill(name="ZAliasDupAliasSkill")

    require(
        len(get_canonical_skill_entries()) == before_count,
        "A name that's already recognized as an ALIAS of an existing skill must not be added as a new entry",
    )


def test_add_canonical_skill_rejects_a_loose_punctuation_variant() -> None:
    add_canonical_skill(name="ZLooseSkillVariant.js")
    before_count = len(get_canonical_skill_entries())

    add_canonical_skill(name="ZLooseSkillVariantJS")

    require(
        len(get_canonical_skill_entries()) == before_count,
        "A punctuation-only spelling variant of an existing skill must not be added as a second entry",
    )


def test_classify_family_deterministically_common_patterns() -> None:
    require(
        classify_family_deterministically("Senior Java Developer") == "Software Engineering",
        "A generic developer title must classify deterministically",
    )
    require(
        classify_family_deterministically("SAP FICO Consultant") == "ERP",
        "A SAP title must classify as ERP deterministically",
    )
    require(
        classify_family_deterministically("Data Engineer") == "Data",
        "AI Engineering/Data-specific keywords must win over the generic 'engineer' catch-all",
    )
    require(
        classify_family_deterministically("Technical Recruiter") == "Recruiting",
        "A recruiter title must classify as Recruiting",
    )


def test_classify_job_title_family_no_llm_configured_stays_unclassified() -> None:
    # A title with no deterministic match and no LiteLLM key configured
    # (this test environment) must never raise or fabricate a guess --
    # it stays exactly as unclassified as it already was.
    family, method = classify_job_title_family("Zzz Totally Novel Title With No Keywords Xyz", ["Data", "Sales"])
    require(family == "Unclassified" and method == "none", f"Expected a clean no-op, got ({family!r}, {method!r})")


def test_approve_job_title_candidate_auto_classifies_when_family_not_given() -> None:
    text = "Job Title: X\n"
    record_taxonomy_candidates(text=text, draft_id=None, sender_domain="autoclassify.com", job_titles=["ZAutoClassifySeniorJavaDeveloperXyz"])

    pending = list_taxonomy_candidates("pending")
    match = next(c for c in pending if c["term"] == "ZAutoClassifySeniorJavaDeveloperXyz")

    result = approve_taxonomy_candidate(match["id"])
    require(result["approved"] is True, f"Approval must still succeed: {result}")

    entries = {e["title"]: e for e in get_job_title_entries()}
    require(
        entries["ZAutoClassifySeniorJavaDeveloperXyz"]["family"] == "Software Engineering",
        f"Approving without an explicit family must auto-classify deterministically, got "
        f"{entries['ZAutoClassifySeniorJavaDeveloperXyz']}",
    )


def test_approve_job_title_candidate_explicit_family_overrides_auto_classify() -> None:
    text = "Job Title: X\n"
    record_taxonomy_candidates(
        text=text, draft_id=None, sender_domain="explicitfamily.com", job_titles=["ZExplicitFamilyDeveloperXyz"]
    )

    pending = list_taxonomy_candidates("pending")
    match = next(c for c in pending if c["term"] == "ZExplicitFamilyDeveloperXyz")

    approve_taxonomy_candidate(match["id"], family="Design")

    entries = {e["title"]: e for e in get_job_title_entries()}
    require(
        entries["ZExplicitFamilyDeveloperXyz"]["family"] == "Design",
        f"An explicitly-given family must win over auto-classification: {entries['ZExplicitFamilyDeveloperXyz']}",
    )


def test_suggest_job_title_family_previews_without_writing() -> None:
    result = suggest_job_title_family("Zzz Suggest Preview SAP Consultant Xyz")
    require(result["family"] == "ERP", f"Wrong suggestion: {result}")

    entries = {e["title"]: e for e in get_job_title_entries()}
    require(
        "Zzz Suggest Preview SAP Consultant Xyz" not in entries,
        "A suggestion must be a preview only -- it must never add a new canonical title",
    )


def test_auto_classify_unclassified_job_titles() -> None:
    add_canonical_job_title(title="ZAutoClassifyBatchDeveloperXyz")  # deterministic hit
    add_canonical_job_title(title="ZAutoClassifyBatchNovelTermWithNoKeywordsXyz")  # no match, no LLM configured

    result = auto_classify_unclassified_job_titles()
    require(result["checked_count"] >= 2, f"Must check every currently-Unclassified title: {result['checked_count']}")

    entries = {e["title"]: e for e in get_job_title_entries()}
    require(
        entries["ZAutoClassifyBatchDeveloperXyz"]["family"] == "Software Engineering",
        f"The deterministic hit must be classified: {entries['ZAutoClassifyBatchDeveloperXyz']}",
    )
    require(
        entries["ZAutoClassifyBatchNovelTermWithNoKeywordsXyz"]["family"] == "Unclassified",
        f"A title neither path could place must stay Unclassified, not get a fabricated guess: "
        f"{entries['ZAutoClassifyBatchNovelTermWithNoKeywordsXyz']}",
    )


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


def test_find_unknown_job_title_rejects_purely_numeric_values() -> None:
    # Defense in depth for the "Position: 1" extraction bug (see
    # app/email_parsing/parsers.py) -- even if a future parser bug hands
    # a non-title value in here, it must never reach the review queue.
    require(find_unknown_job_title("1") is None, "A bare digit must never be queued as a job title")
    require(find_unknown_job_title("25") is None, "A bare number must never be queued as a job title")
    require(
        find_unknown_job_title("ZRealTitleWith1NumberXyz") == "ZRealTitleWith1NumberXyz",
        "A real title that merely contains a digit must still be accepted",
    )


def test_find_unknown_job_title_collapses_location_and_work_mode_variants() -> None:
    # Real production data: the same role showed up as several separate
    # candidates purely because a location/work-mode tag was baked onto
    # the end of the title line.
    require(
        find_unknown_job_title("ZDedupeLead- NY Onsite") == "ZDedupeLead",
        "A trailing '- <location> Onsite/Remote/Hybrid' must be stripped before dedup",
    )
    require(
        find_unknown_job_title("ZDedupeLead IN Brooklyn") == "ZDedupeLead",
        "A trailing 'IN <City>' must be stripped before dedup",
    )
    require(
        find_unknown_job_title("ZDedupeLead (Remote)") == "ZDedupeLead",
        "A trailing '(Remote)'/'(Onsite)'/'(Hybrid)' must be stripped before dedup",
    )
    require(
        find_unknown_job_title("ZDedupeLead (Specialized Automation)") == "ZDedupeLead (Specialized Automation)",
        "A genuinely distinguishing trailing parenthetical must never be stripped",
    )


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


def test_generate_skill_description_without_litellm_configured_returns_none() -> None:
    # No LITELLM_API_KEY in the test environment -- must return None
    # cleanly, never raise, since this whole feature is best-effort by
    # design (a missing description must never break an approval).
    import os

    saved = os.environ.pop("LITELLM_API_KEY", None)
    try:
        result = generate_skill_description("SomeRandomSkillName", category="Tool/Technology")
        require(result is None, f"Expected None with no LiteLLM key configured, got {result!r}")
    finally:
        if saved is not None:
            os.environ["LITELLM_API_KEY"] = saved


def test_set_skill_description_updates_existing_entry() -> None:
    add_canonical_skill(name="ZDescriptionTestSkill")

    ok = set_skill_description("ZDescriptionTestSkill", "A test skill used only in automated checks.")
    require(ok is True, "Setting a description on an existing skill must succeed")

    entries = get_canonical_skill_entries()
    entry = next(e for e in entries if e["name"] == "ZDescriptionTestSkill")
    require(
        entry.get("description") == "A test skill used only in automated checks.",
        f"Expected the description to be persisted, got {entry.get('description')!r}",
    )


def test_set_skill_description_returns_false_for_unknown_skill() -> None:
    ok = set_skill_description("ZNoSuchSkillNameAtAll", "irrelevant")
    require(ok is False, "Setting a description on a skill that doesn't exist must report failure, not raise")


def test_approve_skill_candidate_does_not_fail_without_litellm() -> None:
    # generate_skill_description returning None (no LiteLLM key in this
    # test environment) must not stop the approval itself from
    # succeeding -- description is an optional annotation, never a
    # precondition for approval.
    record_taxonomy_candidates(
        text="Required Skills: ZApproveWithoutDescriptionTestSkill, Java\n",
        draft_id=None,
        sender_domain="nodesctest.com",
    )
    pending = list_taxonomy_candidates(status="pending")
    match = next(c for c in pending if c["term"] == "ZApproveWithoutDescriptionTestSkill")

    result = approve_taxonomy_candidate(match["id"])
    require(result["approved"] is True, "Approval must succeed even when no description could be generated")

    entries = get_canonical_skill_entries()
    entry = next(e for e in entries if e["name"] == "ZApproveWithoutDescriptionTestSkill")
    require(entry.get("description") is None, "No LiteLLM configured -- description must stay unset, not fabricated")


def test_taxonomy_candidates_endpoint_serializes_timestamps() -> None:
    # Real production regression: GET /taxonomy-candidates 500'd the
    # moment a real row existed (an empty result never exercised response
    # serialization). list_taxonomy_candidates() returned raw datetime
    # objects for first_seen_at/last_seen_at, but the response model
    # (TaxonomyCandidateEntry) declares them as str -- FastAPI's response
    # validation rejects a datetime there instead of stringifying it.
    # Exercises the actual HTTP response path, not just the DB function,
    # since that's the layer the bug was actually in.
    record_taxonomy_candidates(
        text="Required Skills: ZTimestampSerializationTestSkill, Java\n",
        draft_id=None,
        sender_domain="tstest.com",
    )

    response = client.get("/taxonomy-candidates")
    require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")

    body = response.json()
    match = next(c for c in body if c["term"] == "ZTimestampSerializationTestSkill")
    require(isinstance(match["first_seen_at"], str), "first_seen_at must serialize as a string")
    require(isinstance(match["last_seen_at"], str), "last_seen_at must serialize as a string")


def test_blocklist_endpoints_serialize_timestamps() -> None:
    # Same class of bug as the taxonomy-candidates endpoint above, in
    # add_block/list_blocks (app/email_parsing/blocklist.py).
    create_response = client.post(
        "/blocklist",
        json={"match_type": "domain", "value": "tstimestamptest.com", "reason": "test fixture"},
    )
    require(
        create_response.status_code == 200,
        f"Expected 200 creating a block, got {create_response.status_code}: {create_response.text}",
    )
    require(
        isinstance(create_response.json()["created_at"], str),
        "POST /blocklist's created_at must serialize as a string",
    )

    list_response = client.get("/blocklist")
    require(list_response.status_code == 200, f"Expected 200, got {list_response.status_code}: {list_response.text}")
    match = next(b for b in list_response.json() if b["value"] == "tstimestamptest.com")
    require(isinstance(match["created_at"], str), "GET /blocklist's created_at must serialize as a string")


def test_human_edit_stamps_source_and_audit_fields() -> None:
    add_canonical_skill(name="ZHumanEditTestSkill")

    result = update_skill_description("ZHumanEditTestSkill", "A skill used only in automated checks.", edited_by="reviewer-1")
    require(result["updated"] is True, "Human edit must succeed")

    entries = get_canonical_skill_entries()
    entry = next(e for e in entries if e["name"] == "ZHumanEditTestSkill")
    require(entry["description"] == "A skill used only in automated checks.", "Description must be persisted")
    require(entry["description_source"] == "human_edited", f"Expected source='human_edited', got {entry.get('description_source')!r}")
    require(entry["description_edited_by"] == "reviewer-1", f"Expected edited_by='reviewer-1', got {entry.get('description_edited_by')!r}")
    require(entry.get("description_edited_at") is not None, "description_edited_at must be stamped")


def test_ai_regeneration_cannot_overwrite_a_human_edit() -> None:
    add_canonical_skill(name="ZProtectedHumanEditSkill")
    update_skill_description("ZProtectedHumanEditSkill", "Human-written definition.", edited_by="reviewer-2")

    raised = False
    try:
        set_skill_description("ZProtectedHumanEditSkill", "AI would overwrite this.", source="ai_generated")
    except SkillDescriptionLocked:
        raised = True

    require(raised, "An ai_generated write must be refused once a description is human_edited")

    entries = get_canonical_skill_entries()
    entry = next(e for e in entries if e["name"] == "ZProtectedHumanEditSkill")
    require(
        entry["description"] == "Human-written definition.",
        f"The human-written description must survive the blocked AI write attempt, got {entry['description']!r}",
    )


def test_update_skill_description_endpoint() -> None:
    add_canonical_skill(name="ZEndpointEditTestSkill")

    response = client.patch(
        "/taxonomy/skills/description",
        json={"name": "ZEndpointEditTestSkill", "description": "Set through the real HTTP endpoint."},
    )
    require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    require(response.json()["updated"] is True, "Endpoint must report the update succeeded")

    entries = get_canonical_skill_entries()
    entry = next(e for e in entries if e["name"] == "ZEndpointEditTestSkill")
    require(entry["description"] == "Set through the real HTTP endpoint.", "Description must actually be written")


def test_update_skill_description_unknown_skill_reports_failure() -> None:
    result = update_skill_description("ZNoSuchSkillForEditTest", "irrelevant")
    require(result["updated"] is False, "Updating a nonexistent skill must report failure, not raise")


def test_taxonomy_writes_go_to_the_runtime_copy_not_the_git_tree() -> None:
    # Real production regression: canonical_skills.json/job_titles.json
    # writes used to go straight into the git-tracked source file
    # (TAXONOMY_DIR), which `docker compose build` recreates from git on
    # every deploy -- an entire description backfill was silently wiped
    # by the next unrelated deploy. Writes must land in _TAXONOMY_RUNTIME_
    # DIR (a persistent volume in production) instead, leaving the
    # git-tracked seed file completely untouched.
    seed_path = TAXONOMY_DIR / "canonical_skills.json"
    seed_text_before = seed_path.read_text(encoding="utf-8")

    add_canonical_skill(name="ZRuntimePersistenceTestSkill")

    require(
        seed_path.read_text(encoding="utf-8") == seed_text_before,
        "The git-tracked seed file must never be modified by a runtime write",
    )

    runtime_path = _writable_taxonomy_path("canonical_skills.json")
    require(
        runtime_path.parent == _TAXONOMY_RUNTIME_DIR,
        f"Expected the runtime copy under {_TAXONOMY_RUNTIME_DIR}, got {runtime_path.parent}",
    )
    require(
        "ZRuntimePersistenceTestSkill" in runtime_path.read_text(encoding="utf-8"),
        "The new skill must actually be persisted in the runtime copy",
    )


def test_runtime_copy_is_not_re_seeded_in_a_fresh_process() -> None:
    # _writable_taxonomy_path is lru_cache'd per-process, so calling it
    # twice in the same test proves nothing about surviving a restart --
    # clear the cache to simulate what a fresh hermes-api process does on
    # its first call after a restart/redeploy: it must find the existing
    # runtime file and use it as-is, not re-copy the seed over it and
    # lose every write made since the copy was first created.
    add_canonical_skill(name="ZPersistAcrossRestartTestSkill")

    _writable_taxonomy_path.cache_clear()
    runtime_path_fresh = _writable_taxonomy_path("canonical_skills.json")

    require(
        "ZPersistAcrossRestartTestSkill" in runtime_path_fresh.read_text(encoding="utf-8"),
        "A fresh process's first call must not re-seed and lose an earlier write",
    )


def test_alias_index_notices_a_write_this_process_never_made() -> None:
    # Real production incident: hermes-api and hermes-graph-consumer are
    # two separate OS processes, each with its own independent in-memory
    # cache. Approving a candidate only ever busts the *approving*
    # process's cache (clear_taxonomy_cache(), called from inside
    # add_canonical_skill) -- the other process kept serving its stale
    # copy for its entire uptime, so a term approved through the review
    # UI could get flagged as "unknown" again by the very next email
    # hermes-graph-consumer parsed, silently re-queuing work a human had
    # just finished. This reproduces that exact shape: warm this
    # process's cache, then change the file WITHOUT calling
    # clear_taxonomy_cache() at all (standing in for "some other process
    # wrote it") -- the mtime check must still pick it up.
    warm_index = build_skill_alias_index()
    require(
        "zmtimecachetestskill" not in warm_index,
        "Fixture skill must not already be present before this test writes it",
    )

    path = _writable_taxonomy_path("canonical_skills.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skills"].append({"name": "ZMtimeCacheTestSkill", "category": "Tool/Technology", "aliases": []})
    path.write_text(json.dumps(data), encoding="utf-8")
    # Force a detectable mtime change regardless of this filesystem's
    # timer resolution -- a real second process's write could otherwise
    # land in the same tick as the warm-up read above.
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))

    index_after = build_skill_alias_index()
    require(
        "zmtimecachetestskill" in index_after,
        "This process's own cache must notice a file change it never triggered itself, with no clear_taxonomy_cache() call",
    )


def test_boilerplate_line_hidden_until_seen_from_enough_distinct_domains() -> None:
    # Real production incident: at a 3-domain threshold this flooded the
    # queue with 13,000+ candidates in under a day, almost all of them
    # generic industry-standard headers/signoffs ("Job Description:",
    # "Key Responsibilities", "Thanks & Regards,") that recur across
    # unrelated companies independent of any shared relay template.
    line = "Zzz Boilerplate Footer Line For Distinct Domain Threshold Test Here"
    domains = [f"bpvendor{i}.com" for i in range(7)]

    for i, domain in enumerate(domains):
        record_boilerplate_line_candidates(f"Real content {i}.\n{line}", f"bp-draft-{i}", domain)

    pending = [c for c in list_taxonomy_candidates("pending") if c["term"] == line]
    require(pending == [], f"A line seen from only 7 distinct domains must not surface yet: {pending}")

    record_boilerplate_line_candidates(f"An eighth posting's content.\n{line}", "bp-draft-8th", "bpvendor8th.com")

    pending = [c for c in list_taxonomy_candidates("pending") if c["term"] == line]
    require(len(pending) == 1, f"A line seen from 8 distinct domains must now be visible: {pending}")
    require(
        set(pending[0]["distinct_senders"]) == set(domains) | {"bpvendor8th.com"},
        f"Wrong distinct_senders: {pending[0]}",
    )


def test_boilerplate_line_ignores_short_generic_headers_and_signoffs() -> None:
    # The exact real production regression -- these are standard
    # professional phrasing every company writes independently, not
    # relay-injected boilerplate, and must never be queued regardless of
    # how many distinct domains they're seen from.
    for line in ["Job Description:", "Key Responsibilities", "Thanks & Regards,", "short"]:
        for i, domain in enumerate([f"bpgeneric{i}.com" for i in range(10)]):
            record_boilerplate_line_candidates(f"Content {i}.\n{line}", f"bp-generic-draft-{i}", domain)

        with cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM taxonomy_candidates WHERE signal_type = 'boilerplate_line' AND term = %s",
                (line,),
            )
            require(cur.fetchone()["n"] == 0, f"A short generic line must never be queued at all: {line!r}")

    record_boilerplate_line_candidates("x" * 250, "bp-draft-long", "bplong.com")
    with cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM taxonomy_candidates WHERE signal_type = 'boilerplate_line' AND term = %s", ("x" * 250,))
        require(cur.fetchone()["n"] == 0, "A too-long line must never be queued")


def test_approving_a_boilerplate_line_strips_it_live_with_no_redeploy() -> None:
    line = "Zzz Approved Boilerplate Line For Live Strip Redeploy Test Right Here"

    for i, domain in enumerate([f"bplive{i}.com" for i in range(8)]):
        record_boilerplate_line_candidates(f"Content {i}.\n{line}", f"bp-live-draft-{i}", domain)

    pending = [c for c in list_taxonomy_candidates("pending") if c["term"] == line]
    require(len(pending) == 1, f"Expected the line to be visible: {pending}")

    result = approve_taxonomy_candidate(pending[0]["id"])
    require(result["approved"] is True, f"Approving a boilerplate_line candidate must succeed: {result}")

    with cursor() as cur:
        cur.execute("SELECT * FROM approved_boilerplate_lines WHERE sample_text = %s", (line,))
        require(cur.fetchone() is not None, "Approving must insert a row into approved_boilerplate_lines")

    require(
        line.strip().lower() in get_approved_boilerplate_lines(),
        "The approved line must be visible via get_approved_boilerplate_lines immediately, no redeploy",
    )

    from app.email_parsing.parsers import parse_requirement_email

    text = (
        "Job Title: Boilerplate Strip Test Developer\n"
        "Required Skills: Java\n\n"
        "Long enough real job description body text here for the evidence check.\n"
        f"{line}\n"
    )
    parsed = parse_requirement_email(text, extra_boilerplate_lines=get_approved_boilerplate_lines())
    require(
        line not in parsed["records"][0]["job_description"],
        f"The approved boilerplate line must be stripped from a real posting immediately: {parsed['records'][0]['job_description']!r}",
    )


def test_boilerplate_signal_type_never_mixed_into_skill_or_job_title_queue() -> None:
    line = "Zzz Boilerplate Never Mixed Into Skills Or Job Titles Test Line Here"
    for i, domain in enumerate([f"bpmix{i}.com" for i in range(8)]):
        record_boilerplate_line_candidates(f"Body {i}.\n{line}", f"bp-mix-draft-{i}", domain)

    pending = list_taxonomy_candidates("pending")
    match = next(c for c in pending if c["term"] == line)
    require(match["signal_type"] == "boilerplate_line", f"Wrong signal_type: {match}")


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

    test_plain_english_stopwords_are_never_queued_as_skill_candidates()
    print("PASS: plain English stopwords are never queued as skill candidates")

    test_taxonomy_candidate_queue_and_approve()
    print("PASS: taxonomy candidate queue accumulates occurrences and approval is live immediately")

    test_taxonomy_candidate_reject()
    print("PASS: rejecting a taxonomy candidate keeps it out of the taxonomy")

    test_edit_taxonomy_candidate_corrects_a_parser_artifact()
    print("PASS: editing a pending candidate's term corrects it before approval")

    test_edit_taxonomy_candidate_rejects_empty_term()
    print("PASS: editing a candidate to an empty term is refused")

    test_edit_taxonomy_candidate_only_touches_pending_rows()
    print("PASS: editing an already-reviewed candidate is refused")

    test_deterministic_glossary_is_used_before_the_llm()
    print("PASS: a known skill's description comes from the deterministic glossary, not the LLM")

    test_bulk_approve_taxonomy_candidates()
    print("PASS: bulk-approving candidates adds all of them to the taxonomy immediately")

    test_bulk_reject_taxonomy_candidates()
    print("PASS: bulk-rejecting candidates keeps all of them out of the taxonomy")

    test_bulk_approve_reports_partial_failure_without_stopping()
    print("PASS: one bad id in a bulk approve does not stop the rest of the batch")

    test_skill_usage_stats_accumulate()
    print("PASS: skill usage stats accumulate across separate drafts")

    test_skill_usage_dedupes_within_one_call()
    print("PASS: a skill repeated within one draft counts as one sighting")

    test_add_canonical_skill_is_idempotent_under_the_lock()
    print("PASS: adding the same canonical skill twice does not duplicate or deadlock")

    test_update_canonical_job_title_renames_and_keeps_old_wording_as_alias()
    print("PASS: renaming a job title keeps the old wording recognized as an alias")

    test_update_canonical_job_title_refuses_a_collision()
    print("PASS: renaming a job title to an already-existing different title is refused")

    test_update_canonical_job_title_family_and_seniority_only()
    print("PASS: reclassifying a job title's family/seniority works without a rename")

    test_update_canonical_job_title_not_found()
    print("PASS: editing a job title that doesn't exist fails cleanly")

    test_bulk_set_job_title_family()
    print("PASS: bulk-setting family reclassifies several job titles in one call")

    test_delete_canonical_job_title_removes_it_without_leaving_an_alias()
    print("PASS: deleting a job title removes it with no alias left behind")

    test_delete_canonical_job_title_not_found()
    print("PASS: deleting a job title that doesn't exist fails cleanly")

    test_bulk_delete_job_titles()
    print("PASS: bulk-deleting removes several job titles in one call")

    test_update_canonical_job_title_applies_a_case_only_rename()
    print("PASS: a case/whitespace-only job title rename actually writes the corrected text")

    test_update_canonical_job_title_computes_related_titles_on_rename()
    print("PASS: related titles are recomputed deterministically when a title is updated")

    test_add_canonical_job_title_rejects_a_duplicate_that_is_only_an_alias()
    print("PASS: adding a title already known only as an alias is rejected as a duplicate")

    test_add_canonical_job_title_rejects_a_loose_punctuation_variant()
    print("PASS: a punctuation-only spelling variant of an existing title is rejected as a duplicate")

    test_compute_related_job_titles_finds_token_overlap_matches()
    print("PASS: related titles are found by shared core keywords, not generic role words alone")

    test_bulk_backfill_related_titles_skips_entries_that_already_have_some()
    print("PASS: backfilling related titles never overwrites an entry that already has some")

    test_find_unknown_skill_terms_ignores_a_loose_punctuation_duplicate()
    print("PASS: a punctuation-only spelling variant of a known skill is not queued as unknown")

    test_find_unknown_job_title_ignores_a_loose_punctuation_duplicate()
    print("PASS: a punctuation-only spelling variant of a known job title is not queued as unknown")

    test_find_unknown_skill_terms_filters_sentence_fragments_and_noise()
    print("PASS: sentence fragments, verb phrases, emails, and person names are never queued as skill candidates")

    test_find_unknown_job_title_filters_sentence_fragments_and_noise()
    print("PASS: sentence fragments, table rows, and person names are never queued as job title candidates")

    test_update_canonical_skill_renames_and_keeps_old_wording_as_alias()
    print("PASS: renaming a skill keeps the old name recognized as an alias")

    test_update_canonical_skill_refuses_a_collision()
    print("PASS: renaming a skill onto an existing different skill is refused")

    test_update_canonical_skill_not_found()
    print("PASS: editing a skill that doesn't exist fails cleanly")

    test_delete_canonical_skill_removes_it_without_leaving_an_alias()
    print("PASS: deleting a skill removes it with no alias left behind")

    test_bulk_delete_skills()
    print("PASS: bulk-deleting removes several skills in one call")

    test_bulk_set_skill_category()
    print("PASS: bulk-setting category reclassifies several skills in one call")

    test_update_canonical_skill_applies_a_case_only_rename()
    print("PASS: a case/whitespace-only skill rename actually writes the corrected text")

    test_add_canonical_skill_rejects_a_duplicate_that_is_only_an_alias()
    print("PASS: adding a skill already known only as an alias is rejected as a duplicate")

    test_add_canonical_skill_rejects_a_loose_punctuation_variant()
    print("PASS: a punctuation-only spelling variant of an existing skill is rejected as a duplicate")

    test_classify_family_deterministically_common_patterns()
    print("PASS: common job title patterns classify deterministically")

    test_classify_job_title_family_no_llm_configured_stays_unclassified()
    print("PASS: a title neither path can place stays cleanly Unclassified, no fabricated guess")

    test_approve_job_title_candidate_auto_classifies_when_family_not_given()
    print("PASS: approving a job title candidate without an explicit family auto-classifies it")

    test_approve_job_title_candidate_explicit_family_overrides_auto_classify()
    print("PASS: an explicitly-given family on approval overrides auto-classification")

    test_suggest_job_title_family_previews_without_writing()
    print("PASS: suggest_job_title_family previews a classification without adding a title")

    test_auto_classify_unclassified_job_titles()
    print("PASS: bulk auto-classify places deterministic hits and leaves genuine misses Unclassified")

    test_unknown_job_title_detected()
    print("PASS: an unrecognized job title is detected, a known one is not")

    test_find_unknown_job_title_rejects_purely_numeric_values()
    print("PASS: a bare digit/number is never queued as a job title candidate")

    test_find_unknown_job_title_collapses_location_and_work_mode_variants()
    print("PASS: location/work-mode title variants collapse into one candidate before dedup")

    test_record_taxonomy_candidates_queues_job_titles()
    print("PASS: an unrecognized job title is queued with signal_type='job_title'")

    test_approve_job_title_candidate_adds_it_live()
    print("PASS: approving a job title candidate adds it to the taxonomy immediately")

    test_intake_pipeline_queues_a_real_unrecognized_job_title()
    print("PASS: real intake with an unrecognized job title queues it for review")

    test_generate_skill_description_without_litellm_configured_returns_none()
    print("PASS: description generation returns None cleanly with no LiteLLM key")

    test_set_skill_description_updates_existing_entry()
    print("PASS: set_skill_description persists a description on an existing skill")

    test_set_skill_description_returns_false_for_unknown_skill()
    print("PASS: set_skill_description reports failure for an unknown skill without raising")

    test_approve_skill_candidate_does_not_fail_without_litellm()
    print("PASS: approving a skill candidate succeeds even when description generation is unavailable")

    test_taxonomy_candidates_endpoint_serializes_timestamps()
    print("PASS: GET /taxonomy-candidates serializes timestamps without a 500")

    test_blocklist_endpoints_serialize_timestamps()
    print("PASS: POST and GET /blocklist serialize timestamps without a 500")

    test_human_edit_stamps_source_and_audit_fields()
    print("PASS: a human edit stamps description_source/edited_by/edited_at")

    test_ai_regeneration_cannot_overwrite_a_human_edit()
    print("PASS: an AI regeneration attempt is refused once a description is human-edited")

    test_update_skill_description_endpoint()
    print("PASS: PATCH /taxonomy/skills/description updates a real skill")

    test_update_skill_description_unknown_skill_reports_failure()
    print("PASS: updating a nonexistent skill reports failure, not an exception")

    test_taxonomy_writes_go_to_the_runtime_copy_not_the_git_tree()
    print("PASS: taxonomy writes land in the persistent runtime copy, never the git-tracked seed file")

    test_runtime_copy_is_not_re_seeded_in_a_fresh_process()
    print("PASS: a fresh process's first taxonomy write does not re-seed and lose earlier writes")

    test_alias_index_notices_a_write_this_process_never_made()
    print("PASS: a process with an already-warm cache notices a taxonomy write it never made itself")

    test_boilerplate_line_hidden_until_seen_from_enough_distinct_domains()
    print("PASS: a boilerplate line stays hidden until seen from 8+ distinct sender domains")

    test_boilerplate_line_ignores_short_generic_headers_and_signoffs()
    print("PASS: short generic headers/signoffs and too-long lines are never queued as boilerplate")

    test_approving_a_boilerplate_line_strips_it_live_with_no_redeploy()
    print("PASS: approving a boilerplate line strips it from postings immediately, no redeploy")

    test_boilerplate_signal_type_never_mixed_into_skill_or_job_title_queue()
    print("PASS: boilerplate_line candidates keep their own signal_type, never mixed with skill/job_title")

    print("HERMES-900 spam/blocklist/taxonomy-candidate check PASSED")


if __name__ == "__main__":
    main()
