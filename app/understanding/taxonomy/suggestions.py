from __future__ import annotations

from app.understanding.taxonomy import suggestion_store
from app.understanding.taxonomy.fuzzy import AUTO_APPROVE_THRESHOLD, fuzzy_match_skill, fuzzy_match_title
from app.understanding.taxonomy.loader import normalize_taxonomy_key
from app.understanding.taxonomy.normalizer import normalize_job_title, normalize_skill


def _clean_observed_term(value: str) -> str:
    return " ".join(value.strip().split())


def _safe_suggested_value(value: str) -> str | None:
    cleaned = _clean_observed_term(value)
    if not cleaned:
        return None

    # Keep this intentionally simple and safe.
    # This is only a suggestion for human review, not an approved taxonomy change.
    return cleaned


def _auto_approve_near_duplicate(
    suggestion_type: str,
    cleaned: str,
    observed_key: str,
    fuzzy_match: dict[str, object],
    source_context: str | None,
) -> dict[str, object]:
    suggestion_store.upsert_suggestion(
        suggestion_type=suggestion_type,
        observed_term=cleaned,
        observed_key=observed_key,
        fuzzy_match=fuzzy_match,
        confidence="high",
        source_context=source_context,
    )

    suggestion_id = suggestion_store.suggestion_id_for(suggestion_type, observed_key)

    suggestion_store.approve_suggestion(
        suggestion_id,
        canonical_value=fuzzy_match["candidate_canonical_value"],
        reviewed_by="hermes_auto_fuzzy_match",
        note=(
            f"Auto-approved: {fuzzy_match['score']}% match to existing term "
            f"'{fuzzy_match['candidate_canonical_value']}' "
            f"(threshold={AUTO_APPROVE_THRESHOLD}). Added as an alias, not a new "
            f"canonical entry - this is the same skill/title, not a new one."
        ),
    )

    return {
        "observed_term": cleaned,
        "suggestion_type": suggestion_type,
        "suggested_canonical_value": fuzzy_match["candidate_canonical_value"],
        "fuzzy_match": fuzzy_match,
        "confidence": "high",
        "status": "auto_approved",
        "source_context": source_context,
    }


def build_skill_suggestion(value: str, source_context: str | None = None) -> dict[str, object] | None:
    cleaned = _clean_observed_term(value)
    if not cleaned:
        return None

    normalized = normalize_skill(cleaned)

    if normalized.get("matched") is True:
        return None

    fuzzy_match = fuzzy_match_skill(cleaned)
    observed_key = normalize_taxonomy_key(cleaned)

    if fuzzy_match and fuzzy_match["score"] >= AUTO_APPROVE_THRESHOLD:
        return _auto_approve_near_duplicate("skill", cleaned, observed_key, fuzzy_match, source_context)

    suggestion_store.upsert_suggestion(
        suggestion_type="skill",
        observed_term=cleaned,
        observed_key=observed_key,
        fuzzy_match=fuzzy_match,
        confidence="low",
        source_context=source_context,
    )

    return {
        "observed_term": cleaned,
        "suggestion_type": "skill",
        "suggested_canonical_value": _safe_suggested_value(cleaned),
        "fuzzy_match": fuzzy_match,
        "confidence": "low",
        "status": "review_required",
        "source_context": source_context,
    }


def build_job_title_suggestion(value: str, source_context: str | None = None) -> dict[str, object] | None:
    cleaned = _clean_observed_term(value)
    if not cleaned:
        return None

    normalized = normalize_job_title(cleaned)

    if normalized.get("matched") is True:
        return None

    fuzzy_match = fuzzy_match_title(cleaned)
    observed_key = normalize_taxonomy_key(cleaned)

    if fuzzy_match and fuzzy_match["score"] >= AUTO_APPROVE_THRESHOLD:
        return _auto_approve_near_duplicate("job_title", cleaned, observed_key, fuzzy_match, source_context)

    suggestion_store.upsert_suggestion(
        suggestion_type="job_title",
        observed_term=cleaned,
        observed_key=observed_key,
        fuzzy_match=fuzzy_match,
        confidence="low",
        source_context=source_context,
    )

    return {
        "observed_term": cleaned,
        "suggestion_type": "job_title",
        "suggested_canonical_value": _safe_suggested_value(cleaned),
        "fuzzy_match": fuzzy_match,
        "confidence": "low",
        "status": "review_required",
        "source_context": source_context,
    }


def build_taxonomy_suggestions(
    skills: list[str] | None = None,
    job_titles: list[str] | None = None,
    source_context: str | None = None,
) -> dict[str, object]:
    # "suggestions" holds only items that still need a human decision -
    # auto_approved holds near-duplicates that were resolved automatically
    # (2026-08-20 product decision: auto-approve near-duplicates only,
    # everything else still requires review - see fuzzy.py
    # AUTO_APPROVE_THRESHOLD). accepted_count reflects real auto-approvals
    # in this call, it is no longer a hardcoded 0.
    suggestions: list[dict[str, object]] = []
    auto_approved: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def _handle(result: dict[str, object] | None) -> None:
        if result is None:
            return

        key = (
            str(result["suggestion_type"]),
            str(result["observed_term"]).lower(),
        )
        if key in seen:
            return

        seen.add(key)

        if result.get("status") == "auto_approved":
            auto_approved.append(result)
        else:
            suggestions.append(result)

    for skill in skills or []:
        _handle(build_skill_suggestion(skill, source_context=source_context))

    for title in job_titles or []:
        _handle(build_job_title_suggestion(title, source_context=source_context))

    return {
        "result_version": "hermes_taxonomy_suggestion_queue_v1",
        "suggestions": suggestions,
        "auto_approved": auto_approved,
        "accepted_count": len(auto_approved),
        "review_required_count": len(suggestions),
    }
