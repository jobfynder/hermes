from __future__ import annotations

import re
from dataclasses import dataclass

from app.understanding.taxonomy.loader import (
    get_canonical_skill_entries,
    get_job_title_entries,
    get_skill_alias_entries,
    get_title_alias_entries,
    load_canonical_skills_taxonomy,
    load_job_titles_taxonomy,
    normalize_taxonomy_key,
)
from app.understanding.taxonomy.normalizer import normalize_job_title, normalize_skill


@dataclass(frozen=True)
class SignalCandidate:
    phrase: str
    normalized: str
    signal_type: str
    match_type: str
    confidence: str


def _safe_phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase.strip())
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def _candidate_key(candidate: SignalCandidate) -> tuple[str, str, str]:
    return (
        candidate.signal_type,
        normalize_taxonomy_key(candidate.phrase),
        candidate.normalized,
    )


def _build_skill_candidates() -> list[SignalCandidate]:
    candidates: list[SignalCandidate] = []

    for entry in get_canonical_skill_entries():
        name = entry.get("name")
        if not name:
            continue

        candidates.append(
            SignalCandidate(
                phrase=name,
                normalized=name,
                signal_type="skill",
                match_type="canonical",
                confidence="high",
            )
        )

        for alias in entry.get("aliases", []):
            normalized = normalize_skill(alias)
            if normalized.get("matched"):
                candidates.append(
                    SignalCandidate(
                        phrase=alias,
                        normalized=str(normalized["normalized"]),
                        signal_type="skill",
                        match_type="alias",
                        confidence=str(normalized["confidence"]),
                    )
                )

    for entry in get_skill_alias_entries():
        alias = entry.get("alias")
        canonical = entry.get("canonical_skill")
        if alias and canonical:
            candidates.append(
                SignalCandidate(
                    phrase=alias,
                    normalized=canonical,
                    signal_type="skill",
                    match_type="alias",
                    confidence=entry.get("confidence", "medium"),
                )
            )

    return _dedupe_candidates(candidates)


def _build_title_candidates() -> list[SignalCandidate]:
    candidates: list[SignalCandidate] = []

    for entry in get_job_title_entries():
        title = entry.get("title")
        if not title:
            continue

        candidates.append(
            SignalCandidate(
                phrase=title,
                normalized=title,
                signal_type="job_title",
                match_type="canonical",
                confidence="high",
            )
        )

        for alias in entry.get("aliases", []):
            normalized = normalize_job_title(alias)
            if normalized.get("matched"):
                candidates.append(
                    SignalCandidate(
                        phrase=alias,
                        normalized=str(normalized["normalized"]),
                        signal_type="job_title",
                        match_type="alias",
                        confidence=str(normalized["confidence"]),
                    )
                )

    for entry in get_title_alias_entries():
        alias = entry.get("alias")
        canonical = entry.get("canonical_title")
        if alias and canonical:
            candidates.append(
                SignalCandidate(
                    phrase=alias,
                    normalized=canonical,
                    signal_type="job_title",
                    match_type="alias",
                    confidence=entry.get("confidence", "medium"),
                )
            )

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[SignalCandidate]) -> list[SignalCandidate]:
    result: dict[tuple[str, str, str], SignalCandidate] = {}

    for candidate in candidates:
        key = _candidate_key(candidate)
        existing = result.get(key)

        if existing is None:
            result[key] = candidate
            continue

        if len(candidate.phrase) > len(existing.phrase):
            result[key] = candidate

    return sorted(
        result.values(),
        key=lambda item: len(item.phrase),
        reverse=True,
    )


def _extract_candidates(text: str, candidates: list[SignalCandidate]) -> list[dict[str, object]]:
    if not text:
        return []

    seen: set[tuple[str, int, int]] = set()
    results: list[dict[str, object]] = []

    for candidate in candidates:
        pattern = _safe_phrase_pattern(candidate.phrase)

        for match in pattern.finditer(text):
            key = (
                candidate.normalized,
                match.start(),
                match.end(),
            )

            if key in seen:
                continue

            seen.add(key)

            results.append(
                {
                    "raw_text": text[match.start():match.end()],
                    "normalized": candidate.normalized,
                    "signal_type": candidate.signal_type,
                    "match_type": candidate.match_type,
                    "confidence": candidate.confidence,
                    "start_index": match.start(),
                    "end_index": match.end(),
                }
            )

    return sorted(
        results,
        key=lambda item: (
            int(item["start_index"]),
            int(item["end_index"]),
            str(item["normalized"]),
        ),
    )


def _dedupe_normalized_signals(signals: list[dict[str, object]]) -> list[dict[str, object]]:
    best_by_name: dict[str, dict[str, object]] = {}

    for signal in signals:
        normalized = str(signal["normalized"])
        existing = best_by_name.get(normalized)

        if existing is None:
            best_by_name[normalized] = signal
            continue

        existing_is_alias = existing.get("match_type") == "alias"
        current_is_canonical = signal.get("match_type") == "canonical"

        if existing_is_alias and current_is_canonical:
            best_by_name[normalized] = signal

    return sorted(
        best_by_name.values(),
        key=lambda item: str(item["normalized"]).lower(),
    )


def extract_taxonomy_signals(text: str) -> dict[str, object]:
    skill_signals = _dedupe_normalized_signals(
        _extract_candidates(text=text, candidates=_build_skill_candidates())
    )
    title_signals = _dedupe_normalized_signals(
        _extract_candidates(text=text, candidates=_build_title_candidates())
    )

    return {
        "result_version": "hermes_taxonomy_signal_extraction_v1",
        "taxonomy_versions": {
            "canonical_skills": load_canonical_skills_taxonomy().get("version", "unknown"),
            "job_titles": load_job_titles_taxonomy().get("version", "unknown"),
        },
        "skills": skill_signals,
        "job_titles": title_signals,
        "unknown_terms": [],
    }
