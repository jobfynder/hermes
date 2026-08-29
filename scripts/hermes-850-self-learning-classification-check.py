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
    test_detect_document_kind_uses_domain_bias_when_content_is_ambiguous()
    print("hermes-850-self-learning-classification-check: all checks passed")
