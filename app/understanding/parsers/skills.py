import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz
import spacy

from app.understanding.taxonomy.loader import (
    get_skill_alias_entries,
    get_skill_entries,
    get_taxonomy_version,
    normalize_taxonomy_key,
)


@lru_cache(maxsize=1)
def get_blank_english_pipeline():
    return spacy.blank("en")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def has_exact_skill_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize_text(text)
    return _skill_pattern(phrase).search(normalized_text) is not None


@lru_cache(maxsize=32768)
def _skill_pattern(phrase: str):
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize_text(phrase)) + r"(?![a-z0-9])")


def skill_match_terms(skill_entry: dict[str, Any], external_aliases: list[str] | None = None) -> list[str]:
    terms = [skill_entry.get("name", "")]
    terms.extend(skill_entry.get("aliases", []))
    terms.extend(external_aliases or [])

    unique = {
        term.strip(): None
        for term in terms
        if isinstance(term, str) and term.strip()
    }
    # Prefer the longest exact phrase present in the page. This prevents a
    # short alias such as "google cloud" from hiding the more useful
    # "Google Cloud Platform" marker when both match the same text.
    return sorted(unique, key=lambda term: (-len(term), term.casefold()))


def fuzzy_match_terms(skill_entry: dict[str, Any], external_aliases: list[str] | None = None) -> list[str]:
    # Learned candidates have not been evaluated for fuzzy matching. Require
    # exact evidence instead of finding a common substring in a whole email.
    if skill_entry.get("source") == "taxonomy_candidate_approved":
        return []
    # Short aliases like js/ts/py are useful for exact matching, but unsafe
    # for fuzzy matching: fuzz.partial_ratio scores a short needle against
    # the best-matching substring of the whole email body, and the shorter
    # the needle, the more likely some coincidental substring elsewhere in
    # a long email scores >=94 by pure chance. Confirmed in production:
    # ".NET" (normalized "net", 3-4 chars) scored a spurious 100% match on
    # an email that never mentions .NET at all. Raising the floor to 6
    # excludes exactly this class of short/generic terms while leaving
    # fuzzy matching for what it's actually for: catching typos in longer,
    # more distinctive terms like "Kubernetes"/"Kubernets".
    return [
        term
        for term in skill_match_terms(skill_entry, external_aliases)
        if len(normalize_text(term)) >= 6
    ]


def extract_skills(
    text: str,
    taxonomy: list[dict[str, Any]] | None = None,
    fuzzy_threshold: int = 94,
    allow_fuzzy: bool = True,
) -> list[dict[str, Any]]:
    skill_entries = taxonomy or get_skill_entries()
    nlp = get_blank_english_pipeline()
    doc = nlp(text or "")

    normalized_text = normalize_text(text)
    token_window_text = " ".join(token.text for token in doc)
    normalized_window = normalize_text(token_window_text)
    found: dict[str, dict[str, Any]] = {}
    aliases_by_skill: dict[str, list[str]] = {}
    for alias in get_skill_alias_entries():
        canonical_key = normalize_taxonomy_key(str(alias.get("canonical_skill") or ""))
        raw_alias = str(alias.get("alias") or "").strip()
        if canonical_key and raw_alias:
            aliases_by_skill.setdefault(canonical_key, []).append(raw_alias)

    for skill_entry in skill_entries:
        skill_name = skill_entry.get("name")

        if not skill_name:
            continue

        external_aliases = aliases_by_skill.get(normalize_taxonomy_key(str(skill_name)), [])
        for term in skill_match_terms(skill_entry, external_aliases):
            if normalize_text(term) in normalized_text and _skill_pattern(term).search(normalized_text) is not None:
                found[skill_name.lower()] = {
                    "name": skill_name,
                    "confidence": 1.0,
                    "method": "exact_phrase" if term == skill_name else "alias_exact_phrase",
                    "matched_term": term,
                    "taxonomy_version": get_taxonomy_version(),
                }
                break

        if skill_name.lower() in found:
            continue

        if not allow_fuzzy:
            continue

        best_score = 0
        best_term = skill_name

        for term in fuzzy_match_terms(skill_entry, external_aliases):
            score = fuzz.partial_ratio(normalize_text(term), normalized_window)

            if score > best_score:
                best_score = score
                best_term = term

        if best_score >= fuzzy_threshold:
            found[skill_name.lower()] = {
                "name": skill_name,
                "confidence": round(best_score / 100, 2),
                "method": "rapidfuzz_partial_ratio",
                "matched_term": best_term,
                "taxonomy_version": get_taxonomy_version(),
            }

    return sorted(
        found.values(),
        key=lambda item: (-item["confidence"], item["name"].lower()),
    )
