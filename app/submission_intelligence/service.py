from app.submission_intelligence.lifecycle import can_transition, workflow_policy
from app.submission_intelligence.models import (
    FollowUp,
    Outcome,
    SubmissionConflict,
    SubmissionEvent,
    SubmissionIntelligenceRequest,
    SubmissionIntelligenceResult,
    SubmissionStage,
)


SUBMIT_DECISIONS = {"submit", "strong_submit", "recommended_submit"}
REVIEW_DECISIONS = {"review", "manual_review", "needs_review"}


def _candidate_key(request: SubmissionIntelligenceRequest) -> str | None:
    consultant = request.consultant
    requirement = request.requirement

    if not consultant.consultant_id or not requirement.job_id:
        return None

    return f"{consultant.consultant_id}:{requirement.job_id}"


def _detect_duplicate_conflicts(request: SubmissionIntelligenceRequest) -> list[SubmissionConflict]:
    key = _candidate_key(request)

    if not key:
        return []

    if key not in request.existing_submission_keys:
        return []

    return [
        SubmissionConflict(
            conflict_type="possible_duplicate_submission",
            severity="high",
            message="This consultant may already be linked to this job.",
            metadata={"submission_key": key},
        )
    ]


def _recommended_stage_from_match(request: SubmissionIntelligenceRequest) -> SubmissionStage:
    current_stage = request.current_stage
    match_result = request.match_result or {}
    decision = str(match_result.get("decision", "")).strip().lower()
    match_score = match_result.get("match_score")

    if current_stage in {"placed", "rejected", "withdrawn", "closed_lost"}:
        return current_stage

    if _detect_duplicate_conflicts(request):
        return "duplicate_risk"

    if decision in SUBMIT_DECISIONS:
        return "matched"

    if decision in REVIEW_DECISIONS:
        return "matched"

    if isinstance(match_score, int | float):
        if match_score >= 75:
            return "matched"

    return current_stage


def _event_from_recommendation(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
) -> list[SubmissionEvent]:
    events: list[SubmissionEvent] = []

    if request.event:
        events.append(request.event)

    if request.current_stage != recommended_stage:
        events.append(
            SubmissionEvent(
                event_type="stage_changed",
                from_stage=request.current_stage,
                to_stage=recommended_stage,
                note=f"Recommended transition from {request.current_stage} to {recommended_stage}.",
                metadata={"source": "hermes-500-foundation"},
            )
        )

    return events


def _build_follow_up(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
    conflicts: list[SubmissionConflict],
) -> FollowUp:
    if conflicts:
        return FollowUp(
            required=True,
            reason="Possible duplicate or workflow conflict needs review before action.",
            priority="high",
            suggested_action="Review existing submissions before proceeding.",
        )

    if recommended_stage == "matched":
        return FollowUp(
            required=True,
            reason="Candidate appears matchable and needs recruiter workflow action.",
            priority="medium",
            suggested_action="Request introduction or submit candidate depending on relationship context.",
        )

    if recommended_stage == "intro_requested":
        return FollowUp(
            required=True,
            reason="Introduction is pending.",
            priority="medium",
            suggested_action="Follow up with the receiving recruiter.",
        )

    return FollowUp(required=False)


def _build_outcome(stage: SubmissionStage) -> Outcome:
    if stage == "placed":
        return Outcome(outcome_type="placed")
    if stage == "rejected":
        return Outcome(outcome_type="rejected")
    if stage == "withdrawn":
        return Outcome(outcome_type="withdrawn")
    if stage == "closed_lost":
        return Outcome(outcome_type="closed_lost")
    if stage == "submitted":
        return Outcome(outcome_type="submitted")
    if stage == "screening":
        return Outcome(outcome_type="screening")
    if stage == "client_submitted":
        return Outcome(outcome_type="client_submitted")
    if stage == "interview":
        return Outcome(outcome_type="interview")
    if stage == "offer":
        return Outcome(outcome_type="offer")
    return Outcome(outcome_type="none")


def _build_reasons(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
    conflicts: list[SubmissionConflict],
) -> list[str]:
    reasons: list[str] = []

    if request.match_result:
        decision = request.match_result.get("decision")
        match_score = request.match_result.get("match_score")
        if decision:
            reasons.append(f"Matching decision available: {decision}.")
        if match_score is not None:
            reasons.append(f"Match score available: {match_score}.")

    if request.taxonomy_context:
        reasons.append("Taxonomy context is available for normalized skill and title reasoning.")

    if recommended_stage != request.current_stage:
        reasons.append(f"Workflow can move from {request.current_stage} to {recommended_stage}.")

    if conflicts:
        reasons.append("Conflict detection found a possible workflow issue.")

    if not reasons:
        reasons.append("No workflow change detected from the current input.")

    return reasons


def _build_risks(conflicts: list[SubmissionConflict]) -> list[str]:
    risks = [conflict.message for conflict in conflicts]
    return risks


def _build_next_actions(
    recommended_stage: SubmissionStage,
    follow_up: FollowUp,
    conflicts: list[SubmissionConflict],
) -> list[str]:
    if conflicts:
        return ["Review duplicate risk before submitting."]

    if follow_up.required and follow_up.suggested_action:
        return [follow_up.suggested_action]

    if recommended_stage == "matched":
        return ["Prepare submission or request introduction."]

    return ["No immediate action required."]


def evaluate_submission_intelligence(
    request: SubmissionIntelligenceRequest,
) -> SubmissionIntelligenceResult:
    conflicts = _detect_duplicate_conflicts(request)
    recommended_stage = _recommended_stage_from_match(request)

    if not can_transition(request.current_stage, recommended_stage):
        conflicts.append(
            SubmissionConflict(
                conflict_type="invalid_stage_transition",
                severity="high",
                message=f"Transition from {request.current_stage} to {recommended_stage} is not allowed.",
                metadata={
                    "from_stage": request.current_stage,
                    "to_stage": recommended_stage,
                },
            )
        )
        recommended_stage = request.current_stage

    events = _event_from_recommendation(request, recommended_stage)
    follow_up = _build_follow_up(request, recommended_stage, conflicts)
    outcome = _build_outcome(recommended_stage)
    reasons = _build_reasons(request, recommended_stage, conflicts)
    risks = _build_risks(conflicts)
    next_actions = _build_next_actions(recommended_stage, follow_up, conflicts)

    return SubmissionIntelligenceResult(
        submission_id=request.submission_id,
        current_stage=request.current_stage,
        recommended_stage=recommended_stage,
        stage_changed=request.current_stage != recommended_stage,
        events=events,
        follow_up=follow_up,
        conflicts=conflicts,
        outcome=outcome,
        reasons=reasons,
        risks=risks,
        next_actions=next_actions,
        handoff={
            "job_id": request.requirement.job_id,
            "consultant_id": request.consultant.consultant_id,
            "workflow_policy": workflow_policy(),
            "source": "hermes-500-submission-intelligence-foundation",
        },
    )
