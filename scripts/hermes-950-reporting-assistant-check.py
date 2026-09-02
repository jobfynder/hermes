"""Checks for the admin reporting dashboard (app/reporting/service.py)
and the natural-language assistant (app/assistant/service.py) that
reads the same data.
"""

import json

from fastapi.testclient import TestClient

from app.assistant.service import answer_query
from app.main import app
from app.reporting.service import (
    get_candidate_queue_health,
    get_dashboard_overview,
    get_llm_cost_trend,
    get_parsing_quality,
    get_taxonomy_overview,
    get_triage_activity,
)
from app.runtime.db import cursor
from app.security.rbac import get_current_user
from app.understanding.taxonomy.candidates import _upsert_candidate

client = TestClient(app)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_taxonomy_overview_has_expected_shape() -> None:
    result = get_taxonomy_overview()
    for key in (
        "total_skills", "total_job_titles",
        "skills_added_7d", "skills_added_30d",
        "job_titles_added_7d", "job_titles_added_30d",
    ):
        require(key in result, f"Missing key {key!r}: {result}")
        require(isinstance(result[key], int), f"{key} must be an int: {result}")


def test_candidate_queue_health_excludes_boilerplate_below_sender_threshold() -> None:
    # Regression test: record_boilerplate_line_candidates deliberately
    # writes a row for EVERY distinct line seen, most from a single
    # company's own one-off content and never meant to surface for
    # review -- list_taxonomy_candidates already filters those out by
    # requiring 8+ distinct sender domains. The first version of
    # get_candidate_queue_health counted raw rows instead, and reported
    # a "37,362 pending boilerplate" backlog that was actually ~6 --
    # every one of those extra rows had only 1 distinct sender.
    _upsert_candidate("boilerplate_line", "ZQueueHealthLowSenderLine", None, "onlyonesender.example.com")

    before = get_candidate_queue_health()

    with cursor() as cur:
        cur.execute(
            "SELECT distinct_senders FROM taxonomy_candidates "
            "WHERE term = 'ZQueueHealthLowSenderLine' AND signal_type = 'boilerplate_line'"
        )
        row = cur.fetchone()
    require(
        len(row["distinct_senders"]) < 8,
        f"Sanity check: fixture must have fewer than 8 distinct senders, got {row['distinct_senders']}",
    )

    after = get_candidate_queue_health()
    require(
        after["boilerplate_line"]["pending_count"] == before["boilerplate_line"]["pending_count"],
        "A boilerplate line seen from fewer than 8 distinct senders must not count toward the "
        f"reported pending backlog: before={before['boilerplate_line']}, after={after['boilerplate_line']}",
    )


def test_triage_activity_groups_by_day() -> None:
    result = get_triage_activity(days=14)
    require(isinstance(result, list), f"Expected a list: {result}")
    for row in result:
        for key in ("date", "approved_automated", "approved_human", "rejected_automated", "rejected_human"):
            require(key in row, f"Missing key {key!r} in triage activity row: {row}")


def test_llm_cost_trend_degrades_gracefully_without_langfuse_configured() -> None:
    # This check environment never has LANGFUSE_* configured -- confirms
    # the cost panel reports "unavailable" rather than raising and
    # taking the rest of the dashboard down with it.
    result = get_llm_cost_trend(days=30)
    require("available" in result, f"Missing 'available' key: {result}")
    require(isinstance(result["days"], list), f"'days' must be a list even when unavailable: {result}")


def test_parsing_quality_has_expected_shape() -> None:
    result = get_parsing_quality(days=7)
    for key in ("total_drafts", "avg_confidence", "needs_review_pct", "by_type"):
        require(key in result, f"Missing key {key!r}: {result}")


def test_dashboard_overview_combines_all_sections() -> None:
    result = get_dashboard_overview()
    for key in ("taxonomy", "queue_health", "triage_activity", "llm_cost", "parsing_quality", "generated_at"):
        require(key in result, f"Missing section {key!r}: {list(result.keys())}")


def test_assistant_answers_gracefully_without_llm_configured() -> None:
    # No LITELLM_API_KEY in this check environment -- the assistant must
    # say so plainly, never crash or silently return an empty answer.
    result = answer_query("How many skills are in the taxonomy?")
    require(result["answer"], f"Expected a non-empty fallback answer: {result}")
    require(result["tool_used"] is None, f"No tool should run without an LLM to plan with: {result}")


def test_assistant_handles_empty_question() -> None:
    result = answer_query("")
    require(result["answer"], f"An empty question must still get a helpful reply, not a crash: {result}")


def test_reports_overview_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.get("/reports/overview")
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
        body = response.json()
        require("taxonomy" in body, f"Missing 'taxonomy' in response: {body}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_assistant_query_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.post("/assistant/query", json={"question": "hello"})
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
        body = response.json()
        require("answer" in body, f"Missing 'answer' in response: {body}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def main() -> None:
    test_taxonomy_overview_has_expected_shape()
    print("PASS: taxonomy overview returns the expected shape")

    test_candidate_queue_health_excludes_boilerplate_below_sender_threshold()
    print("PASS: queue health never counts a low-sender boilerplate line toward the reported backlog")

    test_triage_activity_groups_by_day()
    print("PASS: triage activity groups approvals/rejections by day")

    test_llm_cost_trend_degrades_gracefully_without_langfuse_configured()
    print("PASS: LLM cost trend degrades gracefully without Langfuse configured")

    test_parsing_quality_has_expected_shape()
    print("PASS: parsing quality returns the expected shape")

    test_dashboard_overview_combines_all_sections()
    print("PASS: dashboard overview combines every section in one call")

    test_assistant_answers_gracefully_without_llm_configured()
    print("PASS: the assistant answers gracefully without an LLM configured")

    test_assistant_handles_empty_question()
    print("PASS: an empty question still gets a helpful reply")

    test_reports_overview_endpoint()
    print("PASS: GET /reports/overview returns 200")

    test_assistant_query_endpoint()
    print("PASS: POST /assistant/query returns 200")

    print("HERMES-950 reporting + assistant check PASSED")


if __name__ == "__main__":
    main()
