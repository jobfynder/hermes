import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matching.policy import (
    LOCATION_WEIGHT,
    PREFERRED_SKILL_WEIGHT,
    REQUIRED_SKILL_WEIGHT,
    REVIEW_MIN_REQUIRED_SKILL_SCORE,
    REVIEW_SCORE_THRESHOLD,
    SUBMIT_MIN_YEARS_SCORE,
    SUBMIT_SCORE_THRESHOLD,
    WORK_AUTHORIZATION_WEIGHT,
    YEARS_EXPERIENCE_WEIGHT,
)


def main() -> None:
    weights = [
        REQUIRED_SKILL_WEIGHT,
        PREFERRED_SKILL_WEIGHT,
        YEARS_EXPERIENCE_WEIGHT,
        WORK_AUTHORIZATION_WEIGHT,
        LOCATION_WEIGHT,
    ]
    total = round(sum(weights), 4)
    assert total == 1.0, f"matching weights must total 1.0, got {total}"
    assert SUBMIT_SCORE_THRESHOLD > REVIEW_SCORE_THRESHOLD
    assert 0 <= REVIEW_SCORE_THRESHOLD <= 100
    assert 0 <= SUBMIT_SCORE_THRESHOLD <= 100
    assert 0 <= REVIEW_MIN_REQUIRED_SKILL_SCORE <= 100
    assert 0 <= SUBMIT_MIN_YEARS_SCORE <= 100
    print({"policy": "ok", "weight_total": total, "submit_threshold": SUBMIT_SCORE_THRESHOLD, "review_threshold": REVIEW_SCORE_THRESHOLD})


if __name__ == "__main__":
    main()
