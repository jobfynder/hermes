#!/usr/bin/env python3
"""Focused regression checks for company consolidation and review filtering."""
import os
from uuid import uuid4

from app.companies.service import extract_company
from app.drafts.listing import list_draft_page
from app.runtime.db import cursor, init_schema
from app.understanding.taxonomy import candidates


def require(value, message):
    if not value:
        raise AssertionError(message)


def test_sender_domain_company_fallback():
    draft_id = uuid4()
    row = {
        "draft_id": draft_id, "status": "draft", "channel": "email",
        "metadata": {"sender": {"email": "recruiter@acme-staffing.example"}},
        "payload": {"text": "No signature", "structured_data": {"email_parsing": {"records": []}}},
    }
    observation, reason = extract_company(row)
    require(reason == "linked_sender_domain", f"unexpected reason: {reason}")
    require(observation["domain"] == "acme-staffing.example", "corporate sender domain was not linked")

    row["metadata"]["sender"]["email"] = "person@gmail.com"
    observation, _reason = extract_company(row)
    require(observation is None, "shared email provider must not become a company")


def test_review_filters():
    init_schema()
    wanted, other = uuid4(), uuid4()
    wanted_domain = f"{wanted.hex}.example"
    rows = [
        (wanted, "email", 0.62, f"dev@{wanted_domain}"),
        (other, "telegram", 0.95, "dev@other.example"),
    ]
    with cursor() as cur:
        cur.execute("DELETE FROM drafts WHERE source='scale_ops_check'")
        cur.executemany(
            """INSERT INTO drafts(draft_id,draft_type,status,source,channel,title,confidence,metadata,payload)
               VALUES (%s,'draft_job_requirement','needs_review','scale_ops_check',%s,'Engineer',%s,
                       jsonb_build_object('sender',jsonb_build_object('email',%s::text)),
                       '{"structured_data":{"email_parsing":{"records":[]}}}'::jsonb)""",
            rows,
        )
    result = list_draft_page(channel="email", sender_domain=wanted_domain, confidence_max=0.69)
    require(result["total_count"] == 1, f"filters returned {result['total_count']} rows")
    require(result["items"][0]["draft_id"] == str(wanted), "filters returned the wrong draft")


def test_title_llm_threshold():
    original_entries = candidates.get_job_title_entries
    original_classifier = candidates.classify_job_title_family
    original_apply = candidates.bulk_apply_job_title_families
    original_env = {key: os.environ.get(key) for key in (
        "HERMES_JOB_TITLE_LLM_FALLBACK_ENABLED", "HERMES_JOB_TITLE_LLM_THRESHOLD",
        "HERMES_JOB_TITLE_LLM_MAX_PER_RUN",
    )}
    try:
        candidates.get_job_title_entries = lambda: [
            {"title": "Known Developer", "family": "Software Engineering"},
            *({"title": f"Unknown Role {n}", "family": "Unclassified"} for n in range(102)),
        ]
        candidates.classify_job_title_family = lambda title, families, allow_llm=False: (
            ("Software Engineering", "llm") if allow_llm else ("Unclassified", "none")
        )
        candidates.bulk_apply_job_title_families = lambda mapping: {"updated_count": len(mapping)}
        os.environ.update({
            "HERMES_JOB_TITLE_LLM_FALLBACK_ENABLED": "true",
            "HERMES_JOB_TITLE_LLM_THRESHOLD": "100",
            "HERMES_JOB_TITLE_LLM_MAX_PER_RUN": "50",
        })
        result = candidates.auto_classify_unclassified_job_titles()
        require(result["llm_attempted"] == 2, "LLM must process only the excess above 100")
        require(result["still_unclassified_count"] == 100, "threshold reserve must remain unclassified")
    finally:
        candidates.get_job_title_entries = original_entries
        candidates.classify_job_title_family = original_classifier
        candidates.bulk_apply_job_title_families = original_apply
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_generic_candidate_blocking():
    reason = candidates.taxonomy_candidate_noise_reason
    require(reason("skill", "Knowledge of API Gateway"), "generic knowledge phrase must be blocked")
    require(reason("skill", "⦁ Pandas 2.x"), "bullet-list artifact must be blocked")
    require(reason("skill", "14Y"), "year-count artifact must be blocked")
    require(not reason("skill", "AWS MSK"), "specific technology must remain eligible")
    require(reason("job_title", "Y\nREMOTE\n19\nTABLEAU DEVELOPER"), "table title artifact must be blocked")


def main():
    test_sender_domain_company_fallback()
    test_review_filters()
    test_title_llm_threshold()
    test_generic_candidate_blocking()
    print("HERMES scale operations check PASSED")


if __name__ == "__main__":
    main()
