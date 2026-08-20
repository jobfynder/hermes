from __future__ import annotations

import re
from datetime import datetime, timezone

from app.runtime.events import emit_event
from app.runtime.jsonl_store import read_json, runtime_path, write_json
from app.understanding.taxonomy import overlay
from app.understanding.taxonomy.suggestion_models import (
    SuggestionType,
    TaxonomySuggestionRecord,
)

# Persisted, deduplicated queue for taxonomy suggestions. This sits
# alongside (does not replace) app/understanding/taxonomy/suggestions.py,
# whose build_taxonomy_suggestions() function is a pinned, tested contract
# (scripts/hermes-400-suggestion-queue-check.py) that must keep returning a
# stateless, ungrouped list. This module is what makes review tractable at
# volume: the same observed term seen 50 times across 50 parsed emails
# becomes ONE queue entry with an occurrence_count of 50, not 50 separate
# things to review.

_suggestions: dict[str, TaxonomySuggestionRecord] = {}


def _slug(value: str) -> str:
    cleaned = re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')
    return cleaned or 'blank'


def _suggestion_id(suggestion_type: SuggestionType, observed_key: str) -> str:
    return f'{suggestion_type}__{_slug(observed_key)}'


def suggestion_id_for(suggestion_type: SuggestionType, observed_key: str) -> str:
    return _suggestion_id(suggestion_type, observed_key)


def _suggestion_path(suggestion_id: str):
    return runtime_path('taxonomy_suggestions', f'{suggestion_id}.json')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_suggestion(
    suggestion_type: SuggestionType,
    observed_term: str,
    observed_key: str,
    fuzzy_match: dict[str, object] | None,
    confidence: str,
    source_context: str | None,
) -> TaxonomySuggestionRecord:
    suggestion_id = _suggestion_id(suggestion_type, observed_key)
    existing = get_suggestion(suggestion_id)
    now = _now()

    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        existing.fuzzy_match = fuzzy_match or existing.fuzzy_match

        if source_context and source_context not in existing.source_contexts:
            existing.source_contexts.append(source_context)

        record = existing
    else:
        record = TaxonomySuggestionRecord(
            suggestion_id=suggestion_id,
            suggestion_type=suggestion_type,
            observed_term=observed_term,
            observed_key=observed_key,
            fuzzy_match=fuzzy_match,
            status='review_required',
            confidence=confidence,
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
            source_contexts=[source_context] if source_context else [],
        )

    _suggestions[suggestion_id] = record
    write_json(_suggestion_path(suggestion_id), record.model_dump())
    return record


def get_suggestion(suggestion_id: str) -> TaxonomySuggestionRecord | None:
    if suggestion_id in _suggestions:
        return _suggestions[suggestion_id]

    record = read_json(_suggestion_path(suggestion_id))
    if not record:
        return None

    suggestion = TaxonomySuggestionRecord(**record)
    _suggestions[suggestion_id] = suggestion
    return suggestion


def list_suggestions(status: str | None = None) -> list[TaxonomySuggestionRecord]:
    suggestions_dir = runtime_path('taxonomy_suggestions', '.keep').parent

    for file_path in suggestions_dir.glob('*.json'):
        suggestion_id = file_path.stem
        if suggestion_id not in _suggestions:
            record = read_json(file_path)
            if record:
                _suggestions[suggestion_id] = TaxonomySuggestionRecord(**record)

    items = list(_suggestions.values())

    if status:
        items = [item for item in items if item.status == status]

    return sorted(items, key=lambda item: item.occurrence_count, reverse=True)


def approve_suggestion(
    suggestion_id: str,
    canonical_value: str | None = None,
    reviewed_by: str | None = None,
    note: str | None = None,
) -> TaxonomySuggestionRecord | None:
    suggestion = get_suggestion(suggestion_id)

    if not suggestion:
        return None

    resolved_value = canonical_value or suggestion.observed_term

    if suggestion.suggestion_type == 'skill':
        if canonical_value:
            overlay.add_skill_alias(suggestion.observed_term, canonical_value)
        else:
            overlay.add_canonical_skill(suggestion.observed_term)
    else:
        if canonical_value:
            overlay.add_title_alias(suggestion.observed_term, canonical_value)
        else:
            overlay.add_canonical_job_title(suggestion.observed_term)

    suggestion.status = 'approved'
    suggestion.resolved_canonical_value = resolved_value
    suggestion.reviewed_by = reviewed_by
    suggestion.reviewed_at = _now()
    suggestion.review_note = note

    _suggestions[suggestion_id] = suggestion
    write_json(_suggestion_path(suggestion_id), suggestion.model_dump())

    emit_event(
        'taxonomy.suggestion.approved',
        {
            'suggestion_id': suggestion_id,
            'suggestion_type': suggestion.suggestion_type,
            'observed_term': suggestion.observed_term,
            'resolved_canonical_value': resolved_value,
        },
    )

    return suggestion


def reject_suggestion(
    suggestion_id: str,
    reviewed_by: str | None = None,
    note: str | None = None,
) -> TaxonomySuggestionRecord | None:
    suggestion = get_suggestion(suggestion_id)

    if not suggestion:
        return None

    suggestion.status = 'rejected'
    suggestion.reviewed_by = reviewed_by
    suggestion.reviewed_at = _now()
    suggestion.review_note = note

    _suggestions[suggestion_id] = suggestion
    write_json(_suggestion_path(suggestion_id), suggestion.model_dump())

    emit_event(
        'taxonomy.suggestion.rejected',
        {'suggestion_id': suggestion_id, 'suggestion_type': suggestion.suggestion_type},
    )

    return suggestion
