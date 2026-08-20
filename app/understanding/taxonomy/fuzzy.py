from __future__ import annotations

from rapidfuzz import fuzz, process

from app.understanding.taxonomy.loader import (
    build_skill_alias_index,
    build_title_alias_index,
    normalize_taxonomy_key,
)

# Fuzzy matching here is a hint, never a decision. HERMES-400's safety rule
# is that unknown terms are never auto-approved - this module does not
# change that. It only attaches a 'did you mean X (92%)?' hint to a
# still-review-required suggestion so a human can approve in one click
# instead of researching the term from scratch. It is never used to skip
# creating a suggestion, and it is never wired into normalize_skill() /
# normalize_job_title() - matching stays exact-match deterministic, per the
# HERMES-400 doc's own safety rules.
HINT_THRESHOLD = 82.0


def _fuzzy_match(term: str, index: dict[str, str]) -> dict[str, object] | None:
    key = normalize_taxonomy_key(term)

    if not key or not index:
        return None

    match = process.extractOne(key, index.keys(), scorer=fuzz.WRatio)

    if not match:
        return None

    matched_key, score, _ = match

    if matched_key == key or score < HINT_THRESHOLD:
        return None

    return {
        'candidate_canonical_value': index[matched_key],
        'matched_existing_term': matched_key,
        'score': round(float(score), 1),
    }


def fuzzy_match_skill(term: str) -> dict[str, object] | None:
    return _fuzzy_match(term, build_skill_alias_index())


def fuzzy_match_title(term: str) -> dict[str, object] | None:
    return _fuzzy_match(term, build_title_alias_index())
