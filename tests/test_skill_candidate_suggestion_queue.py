from unittest.mock import patch

from app.understanding.taxonomy.candidates import queue_user_skill_candidate


def test_candidate_queue_checks_normalized_taxonomy_before_writing():
    with patch(
        "app.understanding.taxonomy.candidates.normalize_skill",
        return_value={"matched": True},
    ), patch(
        "app.understanding.taxonomy.candidates._upsert_candidate"
    ) as upsert:
        result = queue_user_skill_candidate("Python")

    assert result == {
        "outcome": "already_known",
        "candidate_id": None,
        "status": "approved",
    }
    upsert.assert_not_called()
