from __future__ import annotations

from app.understanding.taxonomy import suggestion_store
from app.understanding.taxonomy.fuzzy import fuzzy_match_skill, fuzzy_match_title
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


def build_skill_suggestion(value: str, source_context: str | None = None) -> dict[str, object] | None:
    cleaned = _clean_observed_term(value)
    if not cleaned:
        return None

    normalized = normalize_skill(cleaned)

    if normalized.get("matched") is True:
        return None

    fuzzy_match = fuzzy_match_skill(cleaned)

    suggestion_store.upsert_suggestion(
        suggestion_type="skill",
        observed_term=cleaned,
        observed_key=normalize_taxonomy_key(cleaned),
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

    suggestion_store.upsert_suggestion(
        suggestion_type="job_title",
        observed_term=cleaned,
        observed_key=normalize_taxonomy_key(cleaned),
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
    suggestions: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for skill in skills or []:
        suggestion = build_skill_suggestion(skill, source_context=source_context)
        if suggestion is None:
            continue

        key = (
            str(suggestion["suggestion_type"]),
            str(suggestion["observed_term"]).lower(),
        )
        if key not in seen:
            seen.add(key)
            suggestions.append(suggestion)

    for title in job_titles or []:
        suggestion = build_job_title_suggestion(title, source_context=source_context)
        if suggestion is None:
            continue

        key = (
            str(suggestion["suggestion_type"]),
            str(suggestion["observed_term"]).lower(),
        )
        if key not in seen:
            seen.add(key)
            suggestions.append(suggestion)

    return {
        "result_version": "hermes_taxonomy_suggestion_queue_v1",
        "suggestions": suggestions,
        "accepted_count": 0,
        "review_required_count": len(suggestions),
    }
