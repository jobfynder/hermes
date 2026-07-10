from app.submission_intelligence.models import SubmissionStage


WORKFLOW_VERSION = "hermes_submission_workflow_v1"

SUPPORTED_STAGES: list[SubmissionStage] = [
    "discovered",
    "matched",
    "intro_requested",
    "intro_accepted",
    "submitted",
    "screening",
    "client_submitted",
    "interview",
    "offer",
    "placed",
    "rejected",
    "withdrawn",
    "duplicate_risk",
    "closed_lost",
]

TERMINAL_STAGES: list[SubmissionStage] = [
    "placed",
    "rejected",
    "withdrawn",
    "closed_lost",
]

ALLOWED_TRANSITIONS: dict[SubmissionStage, list[SubmissionStage]] = {
    "discovered": ["matched", "intro_requested", "submitted", "duplicate_risk", "closed_lost"],
    "matched": ["intro_requested", "submitted", "duplicate_risk", "closed_lost"],
    "intro_requested": ["intro_accepted", "rejected", "withdrawn", "duplicate_risk"],
    "intro_accepted": ["submitted", "screening", "withdrawn", "duplicate_risk"],
    "submitted": ["screening", "client_submitted", "interview", "rejected", "withdrawn", "duplicate_risk"],
    "screening": ["client_submitted", "interview", "rejected", "withdrawn"],
    "client_submitted": ["interview", "offer", "rejected", "withdrawn"],
    "interview": ["offer", "placed", "rejected", "withdrawn"],
    "offer": ["placed", "rejected", "withdrawn"],
    "duplicate_risk": ["matched", "intro_requested", "submitted", "closed_lost", "withdrawn"],
    "placed": [],
    "rejected": [],
    "withdrawn": [],
    "closed_lost": [],
}


def is_valid_stage(stage: str) -> bool:
    return stage in SUPPORTED_STAGES


def can_transition(from_stage: SubmissionStage, to_stage: SubmissionStage) -> bool:
    if from_stage == to_stage:
        return True
    return to_stage in ALLOWED_TRANSITIONS.get(from_stage, [])


def workflow_policy() -> dict[str, object]:
    return {
        "workflow_version": WORKFLOW_VERSION,
        "supported_stages": SUPPORTED_STAGES,
        "allowed_transitions": ALLOWED_TRANSITIONS,
        "terminal_stages": TERMINAL_STAGES,
    }
