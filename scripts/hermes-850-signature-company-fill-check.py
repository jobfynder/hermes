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
from app.drafts.service import (
    backfill_full_reparse,
    backfill_signature_company_fill,
    create_draft_object,
    get_draft_object,
)
from app.email_parsing.parsers import apply_signature_company_fill
from app.email_parsing.provenance import build_email_parsing_provenance, record_reviewer_correction


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


def _create_stale_pre_fix_draft(source_message_id: str, company_name: str | None = "Indus River Technologies") -> str:
    """Builds a draft the way create_draft_object would have before
    HERMES-850's signature-company-fill shipped: company genuinely
    empty, requires_review True, status therefore 'needs_review' -- but
    with a signature block that (as of the fix) is fully capable of
    resolving it. Bypasses process_channel_intake entirely so the new
    live-path fix doesn't just resolve this at creation time, which
    would defeat the point of testing the backfill against old data.
    """
    email_parsing = {
        "parser": {"name": "hermes_email_deterministic_parser", "uses_llm": False},
        "document_kind": "job_description",
        "records": [_job_record()],
        "record_count": 1,
        "confidence": 0.65,
        "requires_review": True,
        "warnings": ["one_or_more_requirements_require_review"],
    }
    signature = (
        {"detected": True, "contact": {"company_name": {"value": company_name, "confidence": 0.8}}}
        if company_name
        else {"detected": False, "contact": {}}
    )

    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="test_pre_fix_backfill_fixture",
        source_ref=source_message_id,
        channel="email",
        source_message_id=source_message_id,
        payload={
            "text": "fixture text",
            "document_kind": "job_description",
            "structured_data": {"email_parsing": email_parsing, "signature": signature},
        },
        confidence=0.65,
        requires_review=True,
    )
    return draft.draft_id


def test_backfill_dry_run_reports_but_writes_nothing() -> None:
    draft_id = _create_stale_pre_fix_draft("backfill-dry-run-1")

    result = backfill_signature_company_fill(dry_run=True)

    require(draft_id in result["filled_draft_ids"], f"Dry run must still report this draft as fillable: {result}")
    require(draft_id in result["moved_out_of_review_ids"], "Dry run must report it would move out of review")

    unchanged = get_draft_object(draft_id)
    require(unchanged.status == "needs_review", "Dry run must not change status")
    require(unchanged.requires_review is True, "Dry run must not change requires_review")
    record = unchanged.payload["structured_data"]["email_parsing"]["records"][0]
    require(record.get("company") is None, "Dry run must not write the filled company back")


def test_backfill_applies_and_moves_status_out_of_review() -> None:
    draft_id = _create_stale_pre_fix_draft("backfill-apply-1")

    result = backfill_signature_company_fill(dry_run=False)

    require(draft_id in result["filled_draft_ids"], f"Must report this draft as filled: {result}")
    require(draft_id in result["moved_out_of_review_ids"], "Must report it moved out of review")

    updated = get_draft_object(draft_id)
    require(updated.status == "draft", f"Status must move from needs_review to draft, got {updated.status!r}")
    require(updated.requires_review is False, "requires_review must be recomputed to False")
    record = updated.payload["structured_data"]["email_parsing"]["records"][0]
    require(record.get("company") == "Indus River Technologies", f"Company must be persisted, got {record}")


def test_backfill_skips_drafts_with_no_signature_company() -> None:
    draft_id = _create_stale_pre_fix_draft("backfill-no-sig-1", company_name=None)

    result = backfill_signature_company_fill(dry_run=False)

    require(draft_id not in result["filled_draft_ids"], "Must not report a draft with nothing to fill")

    unchanged = get_draft_object(draft_id)
    require(unchanged.status == "needs_review", "A genuinely unresolvable draft must be left exactly as it was")


_YARDI_TEXT = (
    "Subject: YARDI CONSULTANT\n\n"
    "Remove/unsubscribe   |   Update your contact and subscribed mailing list(s)   |   "
    "Subscribe to mailing list(s) to receive requirements & resumes \n\n"
    "From :\nKalyan,\nKK Software Associates\nkalyan@kksoftwareassociates.com\n"
    "Reply to:   kalyan@kksoftwareassociates.com\n\n"
    "Job Title: YARDI CONSULTANT\n"
    "Location: Dallas, TX\n"
    "Required Skills: Yardi Voyager, SQL, Fund Accounting\n\n"
    "Broad understanding of Voyager 7, Core Commercial with international accounting "
    "principles, Investment Management, and Yardi database structure.\n\n"
    "Role Descriptions: Yardi Support\n"
    "1)New User Setups\n"
    "2) Property Setup\n"
    "3) Entity Setup\n"
    "4) If any need to add GL accounts based on request with proper approval\n"
    "5) To provide access past periods based on incidents on monthly basis.\n\n"
    "Skills: Digital, Functional Programming Experience Required: 6-8\n\n"
    "Sign-Up for your account with PROHIRES POWERHOUSE Recruiting Portal to broadcast "
    "requirements & hotlists. \nHire our IT Recruiter at just $499/month ."
)


def _create_stale_draft_pre_relay_and_split_fixes(source_message_id: str) -> str:
    """Simulates a draft parsed and stored BEFORE HERMES-850's
    relay_from_block signature detector and numbered-responsibilities-
    list guard shipped: the real _YARDI_TEXT stored as-is, but the
    STORED parse results shaped exactly as the old, buggy code would
    have produced them -- signature detected with nothing extracted
    (fell through to the platform's own marketing footer), and 5 false
    job-requirement records from the over-eager numbered-list split.
    backfill_signature_company_fill (the narrower, older backfill) is
    powerless here since it only ever reuses this already-wrong stored
    signature -- this is exactly the gap backfill_full_reparse exists
    to close, by re-parsing _YARDI_TEXT itself with the current code.
    """
    stale_records = [
        {**_job_record(job_title="YARDI CONSULTANT" if i == 0 else None, source_section=i + 1), "warnings": ["job_title_missing", "company_missing"] if i else ["company_missing"]}
        for i in range(5)
    ]
    email_parsing = {
        "parser": {"name": "hermes_email_deterministic_parser", "uses_llm": False},
        "document_kind": "job_description",
        "records": stale_records,
        "record_count": 5,
        "confidence": 0.35,
        "requires_review": True,
        "warnings": ["one_or_more_requirements_require_review"],
    }
    signature = {
        "detected": True,
        "method": "structural",
        "contact": {"job_title": {"value": "Hire our IT Recruiter at just $499/month ."}},
    }

    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="test_pre_relay_fix_backfill_fixture",
        source_ref=source_message_id,
        channel="email",
        source_message_id=source_message_id,
        payload={
            "text": _YARDI_TEXT,
            "document_kind": "job_description",
            "structured_data": {"email_parsing": email_parsing, "signature": signature},
        },
        confidence=0.35,
        requires_review=True,
        metadata={"sender": {"email": "kalyan@kksoftwareassociates.com"}},
    )
    return draft.draft_id


def test_full_reparse_recovers_from_stale_pre_relay_fix_data() -> None:
    # Ground-truth checks only (never assert list membership in
    # changed_draft_ids/moved_out_of_review_ids -- both are capped at 50
    # and this backfill runs unlimited across the whole shared test
    # database, which by this point in the suite can easily hold 50+
    # other qualifying draft_job_requirement rows created by earlier
    # check scripts; this draft, being the newest by created_at, could
    # legitimately fall outside a truncated list without that meaning
    # anything went wrong).
    draft_id = _create_stale_draft_pre_relay_and_split_fixes("full-reparse-1")

    backfill_full_reparse(dry_run=False)

    updated = get_draft_object(draft_id)
    signature = updated.payload["structured_data"]["signature"]
    email_parsing = updated.payload["structured_data"]["email_parsing"]
    require(
        signature.get("method") == "relay_from_block",
        f"Stored signature must be replaced by the fresh, correct parse: {signature}",
    )
    require(email_parsing["record_count"] == 1, f"Re-parse must fix the false 5-way split: {email_parsing}")
    require(
        email_parsing["records"][0].get("company") == "KK Software Associates",
        f"Re-parse must recover the company via the new relay_from_block detector: {email_parsing['records'][0]}",
    )
    require(
        email_parsing.get("confidence") == 0.92,
        f"Complete title+skills+company must score 0.92: confidence={email_parsing.get('confidence')} record={email_parsing['records'][0]}",
    )
    require(
        email_parsing.get("requires_review") is False,
        f"email_parsing.requires_review must be False at 0.92 confidence: {email_parsing}",
    )
    require(updated.status == "draft", f"Status must move from needs_review to draft, got {updated.status!r}")


def test_full_reparse_dry_run_writes_nothing() -> None:
    draft_id = _create_stale_draft_pre_relay_and_split_fixes("full-reparse-dry-run-1")

    backfill_full_reparse(dry_run=True)

    unchanged = get_draft_object(draft_id)
    require(unchanged.status == "needs_review", "Dry run must not change status")
    require(
        unchanged.payload["structured_data"]["email_parsing"]["record_count"] == 5,
        "Dry run must not write the re-parsed result back",
    )


def test_full_reparse_never_touches_a_draft_a_human_already_corrected() -> None:
    draft_id = _create_stale_draft_pre_relay_and_split_fixes("full-reparse-human-corrected-1")

    # A reviewer corrected a field on this draft while it still sat in
    # needs_review (allowed today: apply_field_corrections doesn't
    # require the draft to be resolved first) -- that must never be
    # silently discarded by a bulk re-parse.
    record_reviewer_correction(draft_id, "job.company", before=None, after="Reviewer-Confirmed Company LLC")

    backfill_full_reparse(dry_run=False)

    unchanged = get_draft_object(draft_id)
    require(unchanged.status == "needs_review", "Status must stay exactly as the human left it")
    require(
        unchanged.payload["structured_data"]["email_parsing"]["record_count"] == 5,
        "Stored payload must stay exactly as the human left it",
    )


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

    test_backfill_dry_run_reports_but_writes_nothing()
    print("PASS: backfill dry_run reports what would change without writing anything")

    test_backfill_applies_and_moves_status_out_of_review()
    print("PASS: backfill fills company and moves a resolved draft out of needs_review")

    test_backfill_skips_drafts_with_no_signature_company()
    print("PASS: backfill leaves a genuinely unresolvable draft untouched")

    test_full_reparse_recovers_from_stale_pre_relay_fix_data()
    print("PASS: full-reparse backfill recovers company/record-count from stale pre-fix stored data")

    test_full_reparse_dry_run_writes_nothing()
    print("PASS: full-reparse dry_run reports without writing anything")

    test_full_reparse_never_touches_a_draft_a_human_already_corrected()
    print("PASS: full-reparse never overwrites a draft a human already corrected")

    print("hermes-850-signature-company-fill-check: all checks passed")
