ROLE_ACTIONS = {
    "bench_sales_recruiter": [
        "post_hotlist",
        "add_candidate",
        "upload_resume",
        "update_candidate_availability",
        "onboarding_start",
        "onboarding_create_draft",
    ],
    "recruiter": [
        "post_job_requirement",
        "upload_jd",
        "request_candidates",
        "review_submission",
        "onboarding_start",
        "onboarding_create_draft",
    ],
    "consultant": [
        "upload_resume",
        "onboarding_start",
        "onboarding_create_draft",
    ],
    "admin": [
        "post_hotlist",
        "add_candidate",
        "upload_resume",
        "update_candidate_availability",
        "post_job_requirement",
        "upload_jd",
        "request_candidates",
        "review_submission",
        "onboarding_start",
        "onboarding_create_draft",
    ],
    "unknown": [
        "onboarding_start",
    ],
}


def allowed_actions_for(role: str) -> list[str]:
    return ROLE_ACTIONS.get(role, ROLE_ACTIONS["unknown"])


def is_action_allowed(role: str, action: str) -> bool:
    return action in allowed_actions_for(role)
