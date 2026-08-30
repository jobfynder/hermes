"""Checks for self-learning email classification: recording corrections
(app/email_parsing/classification_learning.py), computing a per-sender-
domain bias, and reclassify_draft_object() feeding that loop.
"""
from uuid import uuid4

from app.channels.models import ChannelIntakeRequest, ChannelSender
from app.channels.service import detect_document_kind
from app.drafts.service import create_draft_object, reclassify_draft_object
from app.email_parsing.classification_learning import get_domain_bias, record_classification_correction


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_agreeing_correction_is_a_noop() -> None:
    record_classification_correction(
        draft_id=str(uuid4()),
        sender_email="agree@noop-domain.com",
        predicted_document_kind="hotlist",
        corrected_document_kind="hotlist",
        predicted_confidence=0.9,
    )
    require(
        get_domain_bias("agree@noop-domain.com") is None,
        "A correction that agrees with the prediction must not be recorded as a correction",
    )


def test_no_bias_below_minimum_corrections() -> None:
    record_classification_correction(
        draft_id=str(uuid4()),
        sender_email="single@onecorrection.com",
        predicted_document_kind="job_description",
        corrected_document_kind="hotlist",
        predicted_confidence=0.5,
    )
    require(
        get_domain_bias("single@onecorrection.com") is None,
        "A single correction must not be enough to establish a domain bias (could be a one-off mistake)",
    )


def test_bias_established_after_minimum_corrections() -> None:
    domain = "repeatcorrect.com"
    for i in range(3):
        record_classification_correction(
            draft_id=str(uuid4()),
            sender_email=f"person{i}@{domain}",
            predicted_document_kind="job_description",
            corrected_document_kind="hotlist",
            predicted_confidence=0.5,
        )

    bias = get_domain_bias(f"newcontact@{domain}")
    require(bias is not None, "Three consistent corrections must establish a domain bias")
    require(bias["favored_document_kind"] == "hotlist", f"Wrong favored kind: {bias}")
    require(bias["correction_count"] == 3, f"Wrong correction count: {bias}")
    require(bias["confidence"] == 1.0, f"Wrong confidence: {bias}")


def test_bias_is_per_domain_not_per_full_email() -> None:
    """One staffing company's several recruiters should teach each
    other -- the bias is keyed by domain, not by the exact sending
    address."""
    domain = "sharedcompany.com"
    record_classification_correction(
        draft_id=str(uuid4()),
        sender_email=f"recruiter-a@{domain}",
        predicted_document_kind="job_description",
        corrected_document_kind="hotlist",
        predicted_confidence=0.5,
    )
    record_classification_correction(
        draft_id=str(uuid4()),
        sender_email=f"recruiter-b@{domain}",
        predicted_document_kind="job_description",
        corrected_document_kind="hotlist",
        predicted_confidence=0.5,
    )

    bias = get_domain_bias(f"recruiter-c@{domain}")
    require(bias is not None, "A third, never-before-seen recruiter at the same domain must inherit the bias")
    require(bias["correction_count"] == 2, f"Wrong correction count: {bias}")


def test_domain_bias_never_established_without_email() -> None:
    require(get_domain_bias(None) is None, "No sender email means no domain to look up")
    require(get_domain_bias("not-an-email") is None, "A malformed address must not crash or match anything")


def test_reclassify_updates_draft_type_and_teaches_the_loop() -> None:
    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={"text": "some hotlist-shaped email"},
        confidence=0.55,
        requires_review=True,
        metadata={"sender": {"email": "teach-me@learnfromme.com"}},
    )

    updated = reclassify_draft_object(draft.draft_id, "draft_hotlist")
    require(updated is not None, "Reclassify must succeed for an existing draft")
    require(updated.draft_type == "draft_hotlist", "draft_type must actually change")

    bias = get_domain_bias("anyone@learnfromme.com")
    # Single correction -- not yet enough to bias on its own, but confirm
    # the row landed by adding a second and checking it then applies.
    require(bias is None, "One correction alone must not yet bias (below MIN_CORRECTIONS_FOR_BIAS)")

    draft2 = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={"text": "another one"},
        confidence=0.55,
        requires_review=True,
        metadata={"sender": {"email": "someone-else@learnfromme.com"}},
    )
    reclassify_draft_object(draft2.draft_id, "draft_hotlist")

    bias = get_domain_bias("yet-another@learnfromme.com")
    require(bias is not None, "Two corrections for the same domain must now establish a bias")
    require(bias["favored_document_kind"] == "hotlist", "Wrong favored kind after reclassify")


def test_reclassify_to_non_learnable_type_does_not_teach_the_loop() -> None:
    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={"text": "actually spam or unrelated"},
        confidence=0.55,
        requires_review=True,
        metadata={"sender": {"email": "notlearnable@nothotlistorjob.com"}},
    )

    updated = reclassify_draft_object(draft.draft_id, "draft_channel_note")
    require(updated is not None and updated.draft_type == "draft_channel_note", "draft_type must still change")
    require(
        get_domain_bias("anyone@nothotlistorjob.com") is None,
        "A correction into a type the classifier never chooses must not be fed into the learning loop",
    )


def test_reclassify_unknown_draft_returns_none() -> None:
    require(
        reclassify_draft_object("00000000-0000-0000-0000-000000000000", "draft_hotlist") is None,
        "Reclassifying a nonexistent draft must return None, not raise",
    )


def test_reclassify_reparses_email_content_into_the_corrected_kind() -> None:
    # Real production regression: a genuine job posting was misclassified
    # as document_kind="resume" at intake (content-classification miss on
    # an unstructured vendor-relay email), so create_draft_object stored
    # an empty email_parsing.records[] -- parse_email_business_records
    # correctly refuses to extract job/hotlist fields from a document_kind
    # it wasn't given. A reviewer reclassified it to draft_job_requirement
    # via the "Mark as..." button, which used to only flip the draft_type
    # column: the draft then showed as a job requirement in the list with
    # a stale "Draft Profile" title and zero actual parsed fields --
    # nothing a reviewer could publish. Fixed by re-running the real
    # parser against the draft's own stored text once the correct
    # document_kind is known.
    text = (
        "Subject: Senior SAP ERP Developer | Remote |\n\n"
        "Hiring: Senior SAP ERP Developer | Remote\n\n"
        "We are looking for a Senior SAP ERP Developer with strong expertise "
        "in SAP development, integrations, production support, and modern "
        "SAP technologies.\n\n"
        "Required Skills: SAP ABAP, SAP Fiori, SAP BTP\n\n"
        "Interested candidates, please share your updated resume.\n"
    )

    draft = create_draft_object(
        draft_type="draft_consultant_profile",
        source="channel_text_intake",
        channel="email",
        payload={
            "text": text,
            "document_kind": "resume",
            "structured_data": {
                "document_kind": "resume",
                "email_parsing": {
                    "document_kind": "resume",
                    "records": [],
                    "warnings": ["unsupported_email_document_kind"],
                    "confidence": 0.0,
                    "requires_review": True,
                },
            },
        },
        confidence=0.3,
        requires_review=True,
        metadata={"sender": {"email": "sandy@sapreclassifytest.com"}},
    )

    require(
        draft.payload["structured_data"]["email_parsing"]["records"] == [],
        "Fixture must genuinely start with zero parsed records for this test to be meaningful",
    )

    updated = reclassify_draft_object(draft.draft_id, "draft_job_requirement")

    require(updated is not None, "Reclassify must succeed")
    require(updated.draft_type == "draft_job_requirement", "draft_type must change")

    records = updated.payload["structured_data"]["email_parsing"]["records"]
    require(len(records) == 1, f"Expected the real parser to now produce a record, got {records}")
    require(
        records[0]["job_title"] == "Senior SAP ERP Developer",
        f"Expected the actual job title to be extracted after reparse, got {records[0].get('job_title')!r}",
    )
    require(
        "SAP ABAP" in records[0]["required_skills"],
        f"Expected real skills to be extracted after reparse, got {records[0]['required_skills']}",
    )
    require(
        updated.title == "Senior SAP ERP Developer",
        f"Expected the stale 'Draft Profile' title to be replaced with the real job title, got {updated.title!r}",
    )
    require(
        updated.payload["structured_data"]["document_kind"] == "job_description",
        "structured_data.document_kind must be updated to match the correction, not left as 'resume'",
    )


def test_reclassify_reparse_skipped_for_non_email_channel() -> None:
    # A reclassify on a draft that didn't come from the email channel
    # (e.g. a channel_text_intake test fixture, or a future non-email
    # source) has no raw email text to re-run a deterministic email
    # parser against -- must stay a plain label flip, not raise.
    draft = create_draft_object(
        draft_type="draft_consultant_profile",
        source="channel_text_intake",
        payload={"text": "some content", "document_kind": "resume"},
        confidence=0.3,
        requires_review=True,
    )

    updated = reclassify_draft_object(draft.draft_id, "draft_job_requirement")
    require(updated is not None, "Reclassify must still succeed for a non-email draft")
    require(updated.draft_type == "draft_job_requirement", "draft_type must still change")


def test_detect_document_kind_uses_domain_bias_when_content_is_ambiguous() -> None:
    domain = "ambiguoussender.com"
    for i in range(2):
        record_classification_correction(
            draft_id=str(uuid4()),
            sender_email=f"someone{i}@{domain}",
            predicted_document_kind="job_description",
            corrected_document_kind="hotlist",
            predicted_confidence=0.5,
        )

    # Deliberately unstructured text -- neither parser's own confidence
    # heuristic should land above the classification margin, so this
    # exercises the domain-bias tie-breaker, not real content signal.
    request = ChannelIntakeRequest(
        channel="email",
        source_message_id="ambig-1",
        content_type="text",
        sender=ChannelSender(email=f"newperson@{domain}"),
        text="hey just checking in, following up on our last conversation",
    )

    kind = detect_document_kind(request)
    require(kind == "hotlist", f"Expected the domain bias to break the tie toward hotlist, got {kind}")


if __name__ == "__main__":
    test_agreeing_correction_is_a_noop()
    test_no_bias_below_minimum_corrections()
    test_bias_established_after_minimum_corrections()
    test_bias_is_per_domain_not_per_full_email()
    test_domain_bias_never_established_without_email()
    test_reclassify_updates_draft_type_and_teaches_the_loop()
    test_reclassify_to_non_learnable_type_does_not_teach_the_loop()
    test_reclassify_unknown_draft_returns_none()
    test_reclassify_reparses_email_content_into_the_corrected_kind()
    test_reclassify_reparse_skipped_for_non_email_channel()
    test_detect_document_kind_uses_domain_bias_when_content_is_ambiguous()
    print("hermes-850-self-learning-classification-check: all checks passed")
