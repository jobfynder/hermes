from __future__ import annotations

from app.understanding.taxonomy.loader import (
    build_skill_alias_index,
    build_title_alias_index,
    load_canonical_skills_taxonomy,
    load_job_titles_taxonomy,
    normalize_taxonomy_key,
)


def normalize_skill(value: str) -> dict[str, object]:
    key = normalize_taxonomy_key(value)
    index = build_skill_alias_index()
    canonical = index.get(key)

    taxonomy_version = load_canonical_skills_taxonomy().get("version", "unknown")

    if not key:
        return {
            "input": value,
            "normalized": "",
            "matched": False,
            "match_type": "unknown",
            "confidence": "low",
            "taxonomy_version": taxonomy_version,
        }

    if canonical:
        match_type = "canonical" if normalize_taxonomy_key(canonical) == key else "alias"
        confidence = "high" if match_type == "canonical" else "medium"
        return {
            "input": value,
            "normalized": canonical,
            "matched": True,
            "match_type": match_type,
            "confidence": confidence,
            "taxonomy_version": taxonomy_version,
        }

    return {
        "input": value,
        "normalized": value.strip(),
        "matched": False,
        "match_type": "unknown",
        "confidence": "low",
        "taxonomy_version": taxonomy_version,
    }


def normalize_job_title(value: str) -> dict[str, object]:
    key = normalize_taxonomy_key(value)
    index = build_title_alias_index()
    canonical = index.get(key)

    taxonomy_version = load_job_titles_taxonomy().get("version", "unknown")

    if not key:
        return {
            "input": value,
            "normalized": "",
            "matched": False,
            "match_type": "unknown",
            "confidence": "low",
            "taxonomy_version": taxonomy_version,
        }

    if canonical:
        match_type = "canonical" if normalize_taxonomy_key(canonical) == key else "alias"
        confidence = "high" if match_type == "canonical" else "medium"
        return {
            "input": value,
            "normalized": canonical,
            "matched": True,
            "match_type": match_type,
            "confidence": confidence,
            "taxonomy_version": taxonomy_version,
        }

    return {
        "input": value,
        "normalized": value.strip(),
        "matched": False,
        "match_type": "unknown",
        "confidence": "low",
        "taxonomy_version": taxonomy_version,
    }


def normalize_skills(values: list[str]) -> list[dict[str, object]]:
    return [normalize_skill(value) for value in values]


def normalize_job_titles(values: list[str]) -> list[dict[str, object]]:
    return [normalize_job_title(value) for value in values]
