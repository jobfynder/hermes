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
TERMINAL_STAGES = {"placed", "rejected", "withdrawn", "closed_lost"}


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

    consultant_id = request.consultant.consultant_id
    job_id = request.requirement.job_id

    return [
        SubmissionConflict(
            conflict_type="possible_duplicate_submission",
            severity="high",
            message=(
                f"Consultant {consultant_id} already has a tracked submission key for job {job_id}. "
                "Submitting again risks a duplicate-submission rejection from the client or vendor."
            ),
            metadata={"submission_key": key},
            resolution_steps=[
                "Check the existing submission record for this consultant/job pair before proceeding.",
                "If the prior submission was withdrawn or rejected, confirm that with the client/vendor before resubmitting.",
                "If this is a genuine new attempt (e.g. different rate or resume version), note the reason in the submission record.",
            ],
        )
    ]


def _event_requested_stage(request: SubmissionIntelligenceRequest) -> SubmissionStage | None:
    event = request.event
    if not event:
        return None

    if event.to_stage:
        return event.to_stage

    event_map: dict[str, SubmissionStage] = {
        "match_detected": "matched",
        "intro_requested": "intro_requested",
        "intro_accepted": "intro_accepted",
        "submitted": "submitted",
        "duplicate_risk_detected": "duplicate_risk",
    }

    if event.event_type == "outcome_recorded":
        outcome_type = str(event.metadata.get("outcome_type", "")).strip().lower()
        if outcome_type in {"placed", "rejected", "withdrawn", "closed_lost", "offer", "interview"}:
            return outcome_type  # type: ignore[return-value]

    return event_map.get(event.event_type)


def _recommended_stage_from_match(request: SubmissionIntelligenceRequest) -> SubmissionStage:
    current_stage = request.current_stage
    match_result = request.match_result or {}
    decision = str(match_result.get("decision", "")).strip().lower()
    match_score = match_result.get("match_score")

    if current_stage in TERMINAL_STAGES:
        return current_stage

    if _detect_duplicate_conflicts(request):
        return "duplicate_risk"

    requested_stage = _event_requested_stage(request)
    if requested_stage:
        return requested_stage

    if decision in SUBMIT_DECISIONS:
        return "matched"

    if decision in REVIEW_DECISIONS:
        return "matched"

    if isinstance(match_score, int | float):
        if match_score >= 75:
            return "matched"

    return current_stage


def _event_type_for_transition(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
) -> str:
    if recommended_stage == "matched":
        return "match_detected"
    if recommended_stage == "intro_requested":
        return "intro_requested"
    if recommended_stage == "intro_accepted":
        return "intro_accepted"
    if recommended_stage == "submitted":
        return "submitted"
    if recommended_stage == "duplicate_risk":
        return "duplicate_risk_detected"
    if recommended_stage in {"placed", "rejected", "withdrawn", "closed_lost", "offer", "interview"}:
        return "outcome_recorded"
    return "stage_changed"


def _event_from_recommendation(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
) -> list[SubmissionEvent]:
    events: list[SubmissionEvent] = []

    if request.event:
        events.append(request.event)

    if request.current_stage != recommended_stage:
        event_type = _event_type_for_transition(request, recommended_stage)
        metadata = {"source": "hermes-500-deterministic-rules"}

        if event_type == "outcome_recorded":
            metadata["outcome_type"] = recommended_stage

        events.append(
            SubmissionEvent(
                event_type=event_type,  # type: ignore[arg-type]
                from_stage=request.current_stage,
                to_stage=recommended_stage,
                note=f"Recommended transition from {request.current_stage} to {recommended_stage}.",
                metadata=metadata,
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

    if recommended_stage == "intro_accepted":
        return FollowUp(
            required=True,
            reason="Introduction was accepted and the submission should move forward.",
            priority="high",
            suggested_action="Prepare the consultant submission package.",
        )

    if recommended_stage == "submitted":
        return FollowUp(
            required=True,
            reason="Submission has been sent and needs status tracking.",
            priority="medium",
            suggested_action="Track recruiter response and next screening step.",
        )

    if recommended_stage == "screening":
        return FollowUp(
            required=True,
            reason="Screening is active and needs timely coordination.",
            priority="medium",
            suggested_action="Confirm screening feedback and next step.",
        )

    if recommended_stage == "client_submitted":
        return FollowUp(
            required=True,
            reason="Candidate was submitted to client and requires client-side follow-up.",
            priority="medium",
            suggested_action="Follow up for client feedback.",
        )

    if recommended_stage == "interview":
        return FollowUp(
            required=True,
            reason="Interview stage requires coordination and feedback tracking.",
            priority="high",
            suggested_action="Confirm interview schedule, feedback, and next round.",
        )

    if recommended_stage == "offer":
        return FollowUp(
            required=True,
            reason="Offer stage requires closure tracking.",
            priority="high",
            suggested_action="Track offer details, acceptance, joining date, and closure risk.",
        )

    return FollowUp(required=False)


def _build_outcome(stage: SubmissionStage) -> Outcome:
    if stage == "placed":
        return Outcome(outcome_type="placed", reason="Placement outcome recorded.")
    if stage == "rejected":
        return Outcome(outcome_type="rejected", reason="Rejected outcome recorded.")
    if stage == "withdrawn":
        return Outcome(outcome_type="withdrawn", reason="Withdrawn outcome recorded.")
    if stage == "closed_lost":
        return Outcome(outcome_type="closed_lost", reason="Closed-lost outcome recorded.")
    if stage == "submitted":
        return Outcome(outcome_type="submitted", reason="Submission event recorded.")
    if stage == "screening":
        return Outcome(outcome_type="screening", reason="Screening stage recorded.")
    if stage == "client_submitted":
        return Outcome(outcome_type="client_submitted", reason="Client submission stage recorded.")
    if stage == "interview":
        return Outcome(outcome_type="interview", reason="Interview stage recorded.")
    if stage == "offer":
        return Outcome(outcome_type="offer", reason="Offer stage recorded.")
    return Outcome(outcome_type="none")


def _build_reasons(
    request: SubmissionIntelligenceRequest,
    recommended_stage: SubmissionStage,
    conflicts: list[SubmissionConflict],
) -> list[str]:
    reasons: list[str] = []

    if request.event:
        reasons.append(f"Workflow event available: {request.event.event_type}.")

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

    if recommended_stage in TERMINAL_STAGES:
        return ["No immediate action required. Archive or review for reporting."]

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
                resolution_steps=[
                    "Check the workflow policy (GET /submissions/workflow-policy) for allowed transitions from the current stage.",
                    "Move through the required intermediate stages, or correct the stage if it was set in error.",
                ],
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
