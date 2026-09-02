"""Checks for the admin reporting dashboard (app/reporting/service.py)
and the natural-language assistant (app/assistant/service.py) that
reads the same data.
"""

import json

from fastapi.testclient import TestClient

from app.assistant.service import answer_query
from app.drafts.accuracy import compute_accuracy_summary
from app.main import app
from app.reporting.service import (
    get_ai_dependency_report,
    get_candidate_queue_health,
    get_classification_report,
    get_dashboard_overview,
    get_ingestion_health,
    get_llm_cost_trend,
    get_parsing_quality,
    get_recruitment_intelligence,
    get_review_queue_report,
    get_sender_intelligence,
    get_signature_quality_report,
    get_taxonomy_overview,
    get_triage_activity,
)
from app.runtime.db import cursor
from app.security.rbac import get_current_user
from app.understanding.taxonomy.candidates import _upsert_candidate, _is_noise_skill_term

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
    for key in (
        "today", "taxonomy", "queue_health", "triage_activity", "llm_cost", "parsing_quality",
        "ingestion_health", "classification", "ai_dependency", "review_queue", "signature_quality",
        "generated_at",
    ):
        require(key in result, f"Missing section {key!r}: {list(result.keys())}")


def test_ingestion_health_has_expected_shape() -> None:
    result = get_ingestion_health(days=7)
    for key in ("received", "parsed", "duplicate", "unaccounted", "processing_rate_pct", "received_per_hour", "by_channel"):
        require(key in result, f"Missing key {key!r}: {result}")


def test_ingestion_health_by_channel_only_counts_received_once() -> None:
    # Regression test: intake_log gets a "received" row and later a
    # "parsed" (and sometimes "duplicate") row for the SAME message --
    # summing every status by channel first reported double the real
    # inbound volume. by_channel must match the top-level "received"
    # count exactly (both count the same "received" rows, just grouped
    # differently).
    result = get_ingestion_health(days=7)
    channel_total = sum(result["by_channel"].values())
    require(
        channel_total == result["received"],
        f"by_channel total ({channel_total}) must equal received ({result['received']}), "
        "not double- or triple-count parsed/duplicate rows for the same message",
    )


def test_classification_report_has_expected_shape() -> None:
    result = get_classification_report(days=7)
    require("by_type" in result and "daily" in result, f"Missing keys: {result}")
    for entry in result["by_type"]:
        for key in ("draft_type", "count", "pct_of_total", "avg_confidence"):
            require(key in entry, f"Missing key {key!r} in by_type entry: {entry}")


def test_ai_dependency_report_percentages_sum_to_100() -> None:
    result = get_ai_dependency_report(days=7)
    if result["total_drafts"] > 0:
        total_pct = round((result["parser_only_pct"] or 0) + (result["ai_assisted_pct"] or 0))
        require(
            total_pct == 100,
            f"parser_only_pct + ai_assisted_pct must sum to ~100%, got {total_pct}: {result}",
        )


def test_review_queue_report_has_expected_shape() -> None:
    result = get_review_queue_report(days=7)
    require("by_status" in result and "review_reasons" in result, f"Missing keys: {result}")
    for entry in result["review_reasons"]:
        require("reason" in entry and "count" in entry, f"Malformed review reason entry: {entry}")


def test_signature_quality_report_covers_the_reported_false_extraction_fields() -> None:
    # The user's own screenshot showed the signature parser mis-
    # extracting a full job title/skills phrase as a person's name and
    # company -- confirms the report actually covers those exact fields
    # (full_name/first_name/last_name/company_name), not a stale field
    # list that would silently miss them.
    result = get_signature_quality_report(days=30)
    field_names = {f["field"] for f in result["fields"]}
    for expected in ("full_name", "first_name", "last_name", "company_name", "email", "job_title"):
        require(expected in field_names, f"Signature quality report must cover {expected!r}: {field_names}")


def test_signature_quality_flags_low_confidence_zero_correction_fields_for_spot_check() -> None:
    result = get_signature_quality_report(days=30)
    for entry in result["fields"]:
        require("needs_spot_check" in entry, f"Missing needs_spot_check flag: {entry}")


def test_compute_accuracy_summary_includes_signature_fields() -> None:
    # Regression test for the confidence-vs-correctness gap flagged by
    # the user: precision here is measured from ACTUAL reviewer
    # corrections (field_provenance rows with extractor in
    # recruiter_correction/reviewer_correction), not just the parser's
    # own stated confidence -- a field can show high confidence and
    # still have a real, measured false-positive rate if reviewers have
    # been correcting it.
    result = compute_accuracy_summary(days=30)
    require("signature_fields" in result, f"Missing 'signature_fields': {list(result.keys())}")
    for entry in result["signature_fields"]:
        for key in ("false_positive_rate", "avg_stated_confidence", "calibration_gap"):
            require(key in entry, f"Missing key {key!r} in signature field entry: {entry}")


def test_recruitment_intelligence_has_expected_shape() -> None:
    result = get_recruitment_intelligence(days=30, limit=5)
    for key in (
        "top_skills", "top_skills_all_time", "top_job_titles", "top_locations",
        "top_employment_types", "top_work_authorizations",
        "total_job_records", "rate_specified_count", "rate_specified_pct",
    ):
        require(key in result, f"Missing key {key!r}: {list(result.keys())}")
    require(len(result["top_skills"]) <= 5, f"limit=5 must be respected: {result['top_skills']}")


def test_recruitment_intelligence_top_skills_excludes_noise_terms() -> None:
    # Regression test: "https" was the single most-tracked "skill" in
    # skill_usage_stats (~4,950 occurrences) -- a URL-scheme fragment
    # approved as a taxonomy candidate before the noise filter existed.
    # top_skills must filter through the SAME _is_noise_skill_term()
    # check the daily triage job uses, not just report raw counts.
    result = get_recruitment_intelligence(days=30, limit=15)
    for entry in result["top_skills"]:
        require(
            not _is_noise_skill_term(entry["skill"]),
            f"top_skills must not include noise terms like 'https': {entry}",
        )


def test_sender_intelligence_has_expected_shape() -> None:
    result = get_sender_intelligence(days=30, limit=5)
    for key in ("total_senders", "total_domains", "top_senders", "top_domains"):
        require(key in result, f"Missing key {key!r}: {list(result.keys())}")
    for entry in result["top_senders"]:
        for key in ("sender_email", "total_drafts", "jobs", "hotlists", "avg_confidence", "duplicate_count", "duplicate_pct"):
            require(key in entry, f"Missing key {key!r} in sender entry: {entry}")


def test_sender_intelligence_jobs_hotlists_other_sum_to_total() -> None:
    result = get_sender_intelligence(days=30, limit=15)
    for entry in result["top_senders"]:
        require(
            entry["jobs"] + entry["hotlists"] + entry["other"] == entry["total_drafts"],
            f"jobs+hotlists+other must equal total_drafts: {entry}",
        )


def test_dashboard_overview_includes_recruitment_and_sender_intelligence() -> None:
    result = get_dashboard_overview()
    for key in ("recruitment_intelligence", "sender_intelligence"):
        require(key in result, f"Missing section {key!r}: {list(result.keys())}")


def test_reports_recruitment_intelligence_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.get("/reports/recruitment-intelligence")
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_reports_sender_intelligence_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.get("/reports/sender-intelligence")
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_reports_ingestion_health_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.get("/reports/ingestion-health")
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_reports_signature_quality_endpoint() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "permissions": ["*"]}
    try:
        response = client.get("/reports/signature-quality")
        require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


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

    test_ingestion_health_has_expected_shape()
    print("PASS: ingestion health returns the expected shape")

    test_ingestion_health_by_channel_only_counts_received_once()
    print("PASS: ingestion health by-channel counts match received, not double-counted")

    test_classification_report_has_expected_shape()
    print("PASS: classification report returns the expected shape")

    test_ai_dependency_report_percentages_sum_to_100()
    print("PASS: AI dependency parser-only/AI-assisted percentages sum to 100%")

    test_review_queue_report_has_expected_shape()
    print("PASS: review queue report returns the expected shape")

    test_signature_quality_report_covers_the_reported_false_extraction_fields()
    print("PASS: signature quality report covers the fields from the reported false-extraction incident")

    test_signature_quality_flags_low_confidence_zero_correction_fields_for_spot_check()
    print("PASS: signature quality report flags low-confidence zero-correction fields for spot-check")

    test_compute_accuracy_summary_includes_signature_fields()
    print("PASS: accuracy summary measures signature-field precision from real corrections, not just confidence")

    test_recruitment_intelligence_has_expected_shape()
    print("PASS: recruitment intelligence returns the expected shape")

    test_recruitment_intelligence_top_skills_excludes_noise_terms()
    print("PASS: recruitment intelligence top skills excludes noise terms like 'https'")

    test_sender_intelligence_has_expected_shape()
    print("PASS: sender intelligence returns the expected shape")

    test_sender_intelligence_jobs_hotlists_other_sum_to_total()
    print("PASS: sender intelligence jobs+hotlists+other sums to total_drafts")

    test_dashboard_overview_includes_recruitment_and_sender_intelligence()
    print("PASS: dashboard overview includes recruitment and sender intelligence")

    test_reports_recruitment_intelligence_endpoint()
    print("PASS: GET /reports/recruitment-intelligence returns 200")

    test_reports_sender_intelligence_endpoint()
    print("PASS: GET /reports/sender-intelligence returns 200")

    test_reports_ingestion_health_endpoint()
    print("PASS: GET /reports/ingestion-health returns 200")

    test_reports_signature_quality_endpoint()
    print("PASS: GET /reports/signature-quality returns 200")

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
