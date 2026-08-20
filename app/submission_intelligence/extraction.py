from typing import Any

from app.prompt_runtime.extraction_fallback import run_llm_fallback

DETERMINISTIC_CONFIDENCE_THRESHOLD = 0.70

TRACKER_STAGE_PHRASES: dict[str, list[str]] = {
    "screening": ["moved to screening", "screening call", "internal screen"],
    "submitted": ["submitted the profile", "profile submitted", "sent the resume", "sent over the profile"],
    "client_submitted": ["submitted to the client", "client submission", "sent to client"],
    "interview": ["moved to interview", "scheduled interview", "interview scheduled", "wants to interview", "interview lined up"],
    "offer": ["extended an offer", "offer extended", "received an offer", "got an offer", "offer letter"],
    "placed": ["started the job", "candidate placed", "joined on", "start date confirmed"],
    "rejected": ["client rejected", "not selected", "declined the candidate", "passed on", "rejected the profile"],
    "withdrawn": ["withdrew", "no longer interested", "pulled out", "candidate withdrew"],
}

SUBMISSION_STATUS_PHRASES: dict[str, list[str]] = {
    "submitted": ["submitted", "sent the profile", "sent over"],
    "under_review": ["under review", "client is reviewing", "reviewing the profile"],
    "shortlisted": ["shortlisted", "moved forward", "advancing the candidate"],
    "interview_scheduled": ["interview scheduled", "set up an interview", "interview lined up"],
    "offer_extended": ["offer extended", "extended an offer", "received an offer"],
    "rejected": ["rejected", "not moving forward", "declined", "passed on"],
    "on_hold": ["on hold", "paused", "putting this on hold"],
}


def _match_phrases(message: str, phrase_map: dict[str, list[str]]) -> tuple[str | None, float, list[str]]:
    lower = message.lower()

    for label, phrases in phrase_map.items():
        for phrase in phrases:
            if phrase in lower:
                return label, 0.85, [f"matched_phrase:{phrase}"]

    if len(message.strip()) < 15:
        return None, 0.2, ["message_too_short"]

    return None, 0.35, ["no_known_phrase_matched"]


def extract_tracker_update(
    message: str,
    tracker_context: dict[str, Any],
    allowed_stages: list[str],
) -> dict[str, Any]:
    proposed_stage, confidence, reasons = _match_phrases(message, TRACKER_STAGE_PHRASES)

    result: dict[str, Any] = {
        "proposed_stage": proposed_stage,
        "confidence": confidence,
        "reasons": reasons,
        "llm_fallback": None,
    }

    if confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD:
        outcome = run_llm_fallback(
            prompt_id="jf.job-tracker.update.extract",
            variables={
                "allowed_stages": allowed_stages,
                "message": message,
                "tracker_context": tracker_context,
            },
            source="workflow_tracker_update_extract",
        )
        result["llm_fallback"] = outcome

        if outcome.get("used"):
            extracted = outcome["extracted"]
            candidate_stage = extracted.get("proposed_stage")

            if candidate_stage and (not allowed_stages or candidate_stage in allowed_stages):
                result["proposed_stage"] = candidate_stage
                result["confidence"] = max(confidence, 0.75)
                result["reasons"] = result["reasons"] + ["llm_fallback_used"]

    return result


def extract_submission_status(
    message: str,
    submission_context: dict[str, Any],
    statuses: list[str],
) -> dict[str, Any]:
    proposed_status, confidence, reasons = _match_phrases(message, SUBMISSION_STATUS_PHRASES)

    result: dict[str, Any] = {
        "proposed_status": proposed_status,
        "confidence": confidence,
        "reasons": reasons,
        "llm_fallback": None,
    }

    if confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD:
        outcome = run_llm_fallback(
            prompt_id="jf.submissions.status.extract",
            variables={
                "message": message,
                "statuses": statuses,
                "submission_context": submission_context,
            },
            source="workflow_submission_status_extract",
        )
        result["llm_fallback"] = outcome

        if outcome.get("used"):
            extracted = outcome["extracted"]
            candidate_status = extracted.get("proposed_status")

            if candidate_status and (not statuses or candidate_status in statuses):
                result["proposed_status"] = candidate_status
                result["confidence"] = max(confidence, 0.75)
                result["reasons"] = result["reasons"] + ["llm_fallback_used"]

    return result
