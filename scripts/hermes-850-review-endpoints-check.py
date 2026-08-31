"""Checks for the two new draft-detail endpoints the review frontend
depends on: GET /drafts/{id}/provenance and GET /drafts/{id}/claim.
"""
from fastapi.testclient import TestClient

from app.drafts.service import create_draft_object
from app.email_parsing.provenance import record_field_provenance
from app.main import app


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


client = TestClient(app)


def test_provenance_endpoint_returns_recorded_fields() -> None:
    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={"text": "x"},
        confidence=0.9,
        requires_review=False,
    )
    record_field_provenance(
        draft.draft_id,
        [
            {
                "field_path": "job.job_title",
                "raw_value": "Java Developer",
                "normalized_value": "Java Developer",
                "source_region": None,
                "extractor": "hermes_email_deterministic_parser",
                "extraction_method": "deterministic",
                "confidence": 0.92,
                "value_kind": "EXTRACTED",
            }
        ],
    )

    response = client.get(f"/drafts/{draft.draft_id}/provenance", headers={"Authorization": "Bearer x"})
    require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")
    entries = response.json()
    require(len(entries) == 1, f"Expected 1 provenance entry, got {entries}")
    require(entries[0]["field_path"] == "job.job_title", f"Wrong field_path: {entries[0]}")
    require(entries[0]["extraction_method"] == "deterministic", f"Wrong extraction_method: {entries[0]}")


def test_provenance_endpoint_404_for_unknown_draft() -> None:
    response = client.get(
        "/drafts/00000000-0000-0000-0000-000000000000/provenance", headers={"Authorization": "Bearer x"}
    )
    require(response.status_code == 404, f"Expected 404, got {response.status_code}")


def test_provenance_endpoint_empty_list_for_draft_with_no_provenance() -> None:
    draft = create_draft_object(
        draft_type="draft_channel_note",
        source="channel_text_intake",
        payload={"text": "x"},
        confidence=0.9,
        requires_review=False,
    )
    response = client.get(f"/drafts/{draft.draft_id}/provenance", headers={"Authorization": "Bearer x"})
    require(response.status_code == 200, f"Expected 200, got {response.status_code}")
    require(response.json() == [], "A draft with no provenance rows must return an empty list, not 404")


def test_summary_endpoint_omits_payload_but_computes_title() -> None:
    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={
            "text": "raw email body that must never appear in the summary response",
            "structured_data": {
                "email_parsing": {"records": [{"job_title": "Summary Test Developer", "job_description": "long prose"}]}
            },
        },
        confidence=0.9,
        requires_review=False,
        metadata={"sender": {"email": "recruiter@summarytest.example.com"}},
    )

    response = client.get("/drafts/summary", headers={"Authorization": "Bearer x"})
    require(response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}")

    entries = response.json()
    entry = next(e for e in entries if e["draft_id"] == draft.draft_id)

    require("payload" not in entry, f"The summary row must never include the full payload: {entry.keys()}")
    require(
        entry["display_title"] == "Summary Test Developer",
        f"Expected the record's job_title as display_title, got {entry['display_title']!r}",
    )
    require(
        entry["metadata"]["sender"]["email"] == "recruiter@summarytest.example.com",
        f"metadata must still be present for the sender column: {entry['metadata']}",
    )


def test_summary_endpoint_hotlist_titles() -> None:
    single = create_draft_object(
        draft_type="draft_hotlist",
        source="channel_text_intake",
        payload={
            "structured_data": {"email_parsing": {"records": [{"candidate_name": "Priya Summary"}]}},
        },
        confidence=0.9,
        requires_review=False,
    )
    multi = create_draft_object(
        draft_type="draft_hotlist",
        source="channel_text_intake",
        payload={
            "structured_data": {
                "email_parsing": {"records": [{"candidate_name": "A"}, {"candidate_name": "B"}]}
            },
        },
        confidence=0.9,
        requires_review=False,
    )

    entries = client.get("/drafts/summary", headers={"Authorization": "Bearer x"}).json()
    single_entry = next(e for e in entries if e["draft_id"] == single.draft_id)
    multi_entry = next(e for e in entries if e["draft_id"] == multi.draft_id)

    require(
        single_entry["display_title"] == "Priya Summary",
        f"A one-consultant hotlist must show the candidate's name, got {single_entry['display_title']!r}",
    )
    require(
        multi_entry["display_title"] == "Hotlist — 2 consultants",
        f"A multi-consultant hotlist must show a count, got {multi_entry['display_title']!r}",
    )


def test_claim_endpoint_404_when_no_claim_exists() -> None:
    draft = create_draft_object(
        draft_type="draft_job_requirement",
        source="channel_text_intake",
        payload={"text": "x"},
        confidence=0.9,
        requires_review=False,
    )
    response = client.get(f"/drafts/{draft.draft_id}/claim", headers={"Authorization": "Bearer x"})
    require(response.status_code == 404, f"Expected 404 when no claim exists, got {response.status_code}")


if __name__ == "__main__":
    test_provenance_endpoint_returns_recorded_fields()
    test_provenance_endpoint_404_for_unknown_draft()
    test_provenance_endpoint_empty_list_for_draft_with_no_provenance()
    test_summary_endpoint_omits_payload_but_computes_title()
    test_summary_endpoint_hotlist_titles()
    test_claim_endpoint_404_when_no_claim_exists()
    print("hermes-850-review-endpoints-check: all checks passed")
