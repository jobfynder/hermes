import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz
import spacy

from app.understanding.taxonomy.loader import get_skill_entries, get_taxonomy_version


@lru_cache(maxsize=1)
def get_blank_english_pipeline():
    return spacy.blank("en")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def has_exact_skill_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize_text(text)
    normalized_phrase = normalize_text(phrase)

    pattern = r"(?<![a-z0-9])" + re.escape(normalized_phrase) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def skill_match_terms(skill_entry: dict[str, Any]) -> list[str]:
    terms = [skill_entry.get("name", "")]
    terms.extend(skill_entry.get("aliases", []))

    return [
        term
        for term in terms
        if isinstance(term, str) and term.strip()
    ]


def fuzzy_match_terms(skill_entry: dict[str, Any]) -> list[str]:
    # Short aliases like js/ts/py are useful for exact matching,
    # but unsafe for fuzzy matching because they match inside words like nodejs.
    return [
        term
        for term in skill_match_terms(skill_entry)
        if len(normalize_text(term)) >= 4
    ]


def extract_skills(
    text: str,
    taxonomy: list[dict[str, Any]] | None = None,
    fuzzy_threshold: int = 94,
) -> list[dict[str, Any]]:
    skill_entries = taxonomy or get_skill_entries()
    nlp = get_blank_english_pipeline()
    doc = nlp(text or "")

    normalized_text = normalize_text(text)
    token_window_text = " ".join(token.text for token in doc)
    found: dict[str, dict[str, Any]] = {}

    for skill_entry in skill_entries:
        skill_name = skill_entry.get("name")

        if not skill_name:
            continue

        for term in skill_match_terms(skill_entry):
            if has_exact_skill_phrase(normalized_text, term):
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

        best_score = 0
        best_term = skill_name

        for term in fuzzy_match_terms(skill_entry):
            score = fuzz.partial_ratio(normalize_text(term), normalize_text(token_window_text))

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
