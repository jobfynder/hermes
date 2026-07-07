import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.models import (
    IntegrationErrorSnapshot,
    IntegrationRetryDecisionRequest,
)
from app.integrations.service import decide_retry, get_retry_policy


def test_policy():
    policy = get_retry_policy()
    assert 429 in policy.retryable_status_codes
    assert 401 in policy.non_retryable_status_codes
    assert "timeout" in policy.retryable_error_types


def test_retryable():
    result = decide_retry(
        IntegrationRetryDecisionRequest(
            provider="jobfynder_api",
            event_type="workflow_handoff",
            error=IntegrationErrorSnapshot(
                error_type="timeout",
                status_code=504,
                retry_count=1,
                max_retries=3,
            ),
        )
    )
    assert result.decision == "retry"
    assert result.retry_after_seconds is not None


def test_non_retryable():
    result = decide_retry(
        IntegrationRetryDecisionRequest(
            provider="jobfynder_api",
            event_type="workflow_handoff",
            error=IntegrationErrorSnapshot(
                error_type="validation_error",
                status_code=422,
                retry_count=0,
                max_retries=3,
            ),
        )
    )
    assert result.decision == "do_not_retry"


def test_max_retries():
    result = decide_retry(
        IntegrationRetryDecisionRequest(
            error=IntegrationErrorSnapshot(
                error_type="timeout",
                status_code=504,
                retry_count=3,
                max_retries=3,
            )
        )
    )
    assert result.decision == "do_not_retry"


def test_unknown_needs_review():
    result = decide_retry(
        IntegrationRetryDecisionRequest(
            error=IntegrationErrorSnapshot(
                error_type="unknown_vendor_error",
                status_code=None,
                retry_count=0,
                max_retries=3,
            )
        )
    )
    assert result.decision == "needs_review"


if __name__ == "__main__":
    test_policy()
    test_retryable()
    test_non_retryable()
    test_max_retries()
    test_unknown_needs_review()
    print("HERMES-600 retry policy checks passed.")
