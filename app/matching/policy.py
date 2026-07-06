REQUIRED_SKILL_WEIGHT = 0.55
PREFERRED_SKILL_WEIGHT = 0.15
YEARS_EXPERIENCE_WEIGHT = 0.15
WORK_AUTHORIZATION_WEIGHT = 0.10
LOCATION_WEIGHT = 0.05

SUBMIT_SCORE_THRESHOLD = 80.0
SUBMIT_MIN_YEARS_SCORE = 80.0

REVIEW_SCORE_THRESHOLD = 60.0
REVIEW_MIN_REQUIRED_SKILL_SCORE = 60.0

MATCHER_VERSION = "basic_local_matcher_v1"


def get_active_matching_policy() -> dict[str, object]:
    return {
        "matcher_version": MATCHER_VERSION,
        "weights": {
            "required_skill": REQUIRED_SKILL_WEIGHT,
            "preferred_skill": PREFERRED_SKILL_WEIGHT,
            "years_experience": YEARS_EXPERIENCE_WEIGHT,
            "work_authorization": WORK_AUTHORIZATION_WEIGHT,
            "location": LOCATION_WEIGHT,
        },
        "thresholds": {
            "submit_score": SUBMIT_SCORE_THRESHOLD,
            "submit_min_years_score": SUBMIT_MIN_YEARS_SCORE,
            "review_score": REVIEW_SCORE_THRESHOLD,
            "review_min_required_skill_score": REVIEW_MIN_REQUIRED_SKILL_SCORE,
        },
    }
