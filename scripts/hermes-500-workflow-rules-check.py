import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.submission_intelligence.models import (
    SubmissionEvent,
    SubmissionIntelligenceRequest,
)
from app.submission_intelligence.service import evaluate_submission_intelligence


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_intro_requested_event_check():
    request = SubmissionIntelligenceRequest(
        current_stage="matched",
        event=SubmissionEvent(
            event_type="intro_requested",
            note="Bench sales recruiter requested introduction.",
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "intro_requested", "intro requested stage")
    assert_equal(result.events[-1].event_type, "intro_requested", "intro requested event")
    assert result.follow_up.required is True
    assert_equal(result.follow_up.priority, "medium", "intro requested priority")


def run_intro_accepted_event_check():
    request = SubmissionIntelligenceRequest(
        current_stage="intro_requested",
        event=SubmissionEvent(
            event_type="intro_accepted",
            note="Recruiter accepted the introduction.",
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "intro_accepted", "intro accepted stage")
    assert_equal(result.events[-1].event_type, "intro_accepted", "intro accepted event")
    assert result.follow_up.required is True
    assert_equal(result.follow_up.priority, "high", "intro accepted priority")


def run_submitted_event_check():
    request = SubmissionIntelligenceRequest(
        current_stage="intro_accepted",
        event=SubmissionEvent(
            event_type="submitted",
            note="Consultant submitted to recruiter.",
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "submitted", "submitted stage")
    assert_equal(result.events[-1].event_type, "submitted", "submitted event")
    assert_equal(result.outcome.outcome_type, "submitted", "submitted outcome")
    assert result.follow_up.required is True


def run_offer_outcome_check():
    request = SubmissionIntelligenceRequest(
        current_stage="interview",
        event=SubmissionEvent(
            event_type="outcome_recorded",
            metadata={"outcome_type": "offer"},
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "offer", "offer stage")
    assert_equal(result.events[-1].event_type, "outcome_recorded", "offer event")
    assert_equal(result.outcome.outcome_type, "offer", "offer outcome")
    assert result.follow_up.required is True
    assert_equal(result.follow_up.priority, "high", "offer priority")


def run_placed_outcome_check():
    request = SubmissionIntelligenceRequest(
        current_stage="offer",
        event=SubmissionEvent(
            event_type="outcome_recorded",
            metadata={"outcome_type": "placed"},
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "placed", "placed stage")
    assert_equal(result.outcome.outcome_type, "placed", "placed outcome")
    assert result.follow_up.required is False


def run_invalid_transition_check():
    request = SubmissionIntelligenceRequest(
        current_stage="discovered",
        event=SubmissionEvent(
            event_type="outcome_recorded",
            metadata={"outcome_type": "placed"},
        ),
    )

    result = evaluate_submission_intelligence(request)

    assert_equal(result.recommended_stage, "discovered", "invalid transition keeps stage")
    assert_equal(result.stage_changed, False, "invalid transition stage_changed")
    assert result.conflicts
    assert_equal(result.conflicts[0].conflict_type, "invalid_stage_transition", "invalid conflict type")
    assert result.follow_up.required is True
    assert_equal(result.follow_up.priority, "high", "invalid transition priority")


if __name__ == "__main__":
    run_intro_requested_event_check()
    run_intro_accepted_event_check()
    run_submitted_event_check()
    run_offer_outcome_check()
    run_placed_outcome_check()
    run_invalid_transition_check()
    print("HERMES-500 workflow rules checks passed.")
