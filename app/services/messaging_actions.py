from typing import Any

from app.prompt_runtime.extraction_fallback import run_llm_fallback

DETERMINISTIC_CONFIDENCE_THRESHOLD = 0.70

ACTION_PHRASES: dict[str, list[str]] = {
    "send_resume": ["send the resume", "share the resume", "send over the profile", "share the profile"],
    "schedule_call": ["schedule a call", "set up a call", "can we talk", "hop on a call"],
    "schedule_interview": ["set up an interview", "schedule an interview", "arrange an interview"],
    "follow_up": ["follow up", "any update", "checking in", "circling back"],
    "confirm_availability": ["are you available", "confirm availability", "still interested"],
}


def _detect_actions(messages: list[str]) -> tuple[list[str], float, list[str]]:
    combined = " ".join(messages).lower()
    detected: list[str] = []
    reasons: list[str] = []

    for action, phrases in ACTION_PHRASES.items():
        for phrase in phrases:
            if phrase in combined:
                detected.append(action)
                reasons.append(f"matched_phrase:{phrase}")
                break

    if detected:
        return detected, 0.85, reasons

    if len(combined.strip()) < 15:
        return [], 0.2, ["message_too_short"]

    return [], 0.35, ["no_known_action_phrase_matched"]


def extract_messaging_actions(
    messages: list[str],
    allowed_actions: list[str],
    context: dict[str, Any],
) -> dict[str, Any]:
    detected, confidence, reasons = _detect_actions(messages)

    if allowed_actions:
        detected = [action for action in detected if action in allowed_actions]

    result: dict[str, Any] = {
        "proposed_actions": detected,
        "confidence": confidence,
        "reasons": reasons,
        "llm_fallback": None,
    }

    if confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD or not detected:
        outcome = run_llm_fallback(
            prompt_id="jf.messaging.actions.extract",
            variables={
                "allowed_actions": allowed_actions,
                "context": context,
                "messages": messages,
            },
            source="messaging_actions_extract",
        )
        result["llm_fallback"] = outcome

        if outcome.get("used"):
            extracted = outcome["extracted"]
            candidate_actions = extracted.get("proposed_actions") or extracted.get("actions") or []

            if allowed_actions:
                candidate_actions = [action for action in candidate_actions if action in allowed_actions]

            if candidate_actions:
                result["proposed_actions"] = candidate_actions
                result["confidence"] = max(confidence, 0.75)
                result["reasons"] = result["reasons"] + ["llm_fallback_used"]

    return result
