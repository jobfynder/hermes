from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz

from app.understanding.parsers.job_description_fields import (
    extract_preferred_skills_text,
    extract_required_skills_text,
)
from app.understanding.parsers.skills import extract_skills
from app.understanding.taxonomy.loader import (
    build_skill_alias_index,
    get_canonical_skill_entries,
    get_skill_alias_entries,
    get_taxonomy_cache_revision,
    normalize_taxonomy_key,
)
from app.understanding.taxonomy.identity import stable_skill_id


_FUZZY_THRESHOLD = 94
_MAX_SEARCH_RESULTS = 50
_CONTEXT_ORDER = ("required", "preferred", "excluded", "mentioned")


def skill_id_for(entry: dict[str, Any]) -> str:
    return str(entry.get("skill_id") or stable_skill_id(str(entry.get("name", ""))))


@lru_cache(maxsize=8)
def _taxonomy_revision_for_cache(cache_revision: tuple) -> str:
    """Content-addressed version so every process invalidates stale cards."""
    payload = {
        "skills": get_canonical_skill_entries(),
        "aliases": get_skill_alias_entries(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"skills-{hashlib.sha256(encoded).hexdigest()[:16]}"


def taxonomy_revision() -> str:
    return _taxonomy_revision_for_cache(get_taxonomy_cache_revision())


def _entry_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for entry in get_canonical_skill_entries():
        name = str(entry.get("name") or "")
        if not name or entry.get("status", "active") != "active":
            continue
        by_name[normalize_taxonomy_key(name)] = entry
        by_id[skill_id_for(entry)] = entry
    return by_name, by_id


def _all_terms(entry: dict[str, Any]) -> list[str]:
    canonical_name = str(entry.get("name") or "")
    terms = [canonical_name, *entry.get("aliases", [])]
    for alias in get_skill_alias_entries():
        if normalize_taxonomy_key(str(alias.get("canonical_skill") or "")) == normalize_taxonomy_key(canonical_name):
            terms.append(str(alias.get("alias") or ""))
    return sorted({term.strip() for term in terms if isinstance(term, str) and term.strip()}, key=str.casefold)


def resolve(term: str, allow_fuzzy: bool = True) -> dict[str, Any]:
    raw = term.strip()
    revision = taxonomy_revision()
    key = normalize_taxonomy_key(raw)
    by_name, _ = _entry_indexes()
    canonical = build_skill_alias_index().get(key)
    if canonical:
        entry = by_name.get(normalize_taxonomy_key(canonical))
        if entry:
            canonical_key = normalize_taxonomy_key(str(entry["name"]))
            match_type = "canonical" if key == canonical_key else "alias"
            return {
                "input": term,
                "matched": True,
                "skill_id": skill_id_for(entry),
                "canonical_name": entry["name"],
                "matched_term": raw,
                "match_type": match_type,
                "confidence": 1.0 if match_type == "canonical" else 0.99,
                "taxonomy_version": revision,
            }

    # Fuzzy resolution is deliberately unavailable for short terms and
    # requires a decisive best match. This prevents ambiguous acronyms from
    # silently becoming a different skill.
    if allow_fuzzy and len(key) >= 6:
        candidates: list[tuple[int, dict[str, Any], str]] = []
        for entry in by_name.values():
            for candidate_term in _all_terms(entry):
                candidate_key = normalize_taxonomy_key(candidate_term)
                if len(candidate_key) < 6:
                    continue
                score = int(fuzz.ratio(key, candidate_key))
                candidates.append((score, entry, candidate_term))
        candidates.sort(key=lambda item: (-item[0], str(item[1].get("name", "")).casefold()))
        if candidates:
            best = candidates[0]
            runner_up = candidates[1][0] if len(candidates) > 1 else 0
            if best[0] >= _FUZZY_THRESHOLD and best[0] - runner_up >= 3:
                return {
                    "input": term,
                    "matched": True,
                    "skill_id": skill_id_for(best[1]),
                    "canonical_name": best[1]["name"],
                    "matched_term": raw,
                    "match_type": "fuzzy",
                    "confidence": round(best[0] / 100, 2),
                    "taxonomy_version": revision,
                }

    return {
        "input": term,
        "matched": False,
        "skill_id": None,
        "canonical_name": None,
        "matched_term": raw or None,
        "match_type": "unknown",
        "confidence": 0.0,
        "taxonomy_version": revision,
    }


def resolve_batch(terms: list[str]) -> dict[str, Any]:
    # Keep first occurrence and input order. This gives Chrome a stable,
    # compact response and avoids repeated work on duplicate page terms.
    unique = list(dict.fromkeys(term.strip() for term in terms if term.strip()))
    revision = taxonomy_revision()
    return {
        "result_version": "hermes_skill_intelligence_resolve_v1",
        "taxonomy_version": revision,
        "results": [resolve(term) for term in unique],
    }


def _relationship_rows(entry: dict[str, Any]) -> list[dict[str, str]]:
    by_name, _ = _entry_indexes()
    explicit = entry.get("relationships") or []
    raw_rows = explicit or [
        {"type": "commonly_used_with", "skill": name}
        for name in entry.get("related_skills", [])
    ]
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_rows:
        if isinstance(raw, str):
            relation_type, related_name = "commonly_used_with", raw
        else:
            relation_type = str(raw.get("type") or "commonly_used_with")
            related_name = str(raw.get("skill") or raw.get("name") or "")
        related = by_name.get(normalize_taxonomy_key(related_name))
        if not related:
            continue
        identity = (relation_type, skill_id_for(related))
        if identity in seen:
            continue
        seen.add(identity)
        rows.append({"type": relation_type, "skill_id": identity[1], "name": str(related["name"])})
    return rows


def skill_card(entry: dict[str, Any], matched_term: str | None = None, match_type: str | None = None,
               confidence: float | None = None) -> dict[str, Any]:
    aliases = [
        term for term in _all_terms(entry)
        if normalize_taxonomy_key(term) != normalize_taxonomy_key(str(entry["name"]))
    ]
    return {
        "skill_id": skill_id_for(entry),
        "canonical_name": entry["name"],
        "matched_term": matched_term,
        "match_type": match_type,
        "confidence": confidence,
        "category": entry.get("category") or "Uncategorized",
        "subcategory": entry.get("subcategory"),
        "definition": entry.get("short_definition") or entry.get("description"),
        "recruiter_explanation": entry.get("recruiter_explanation"),
        "aliases": aliases,
        "relationships": _relationship_rows(entry),
        "related_roles": entry.get("related_roles", []),
        "taxonomy_version": taxonomy_revision(),
    }


def get_skill(skill_id: str) -> dict[str, Any] | None:
    _, by_id = _entry_indexes()
    entry = by_id.get(skill_id)
    return skill_card(entry) if entry else None


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    key = normalize_taxonomy_key(query)
    if not key:
        return []
    by_name, _ = _entry_indexes()
    scored: list[tuple[int, str, dict[str, Any], str]] = []
    for entry in by_name.values():
        best_score = 0
        best_term = str(entry["name"])
        for term in _all_terms(entry):
            term_key = normalize_taxonomy_key(term)
            if term_key.startswith(key):
                score = 300 - len(term_key)
            elif key in term_key:
                score = 200 - term_key.index(key)
            else:
                score = int(fuzz.ratio(key, term_key)) if len(key) >= 4 else 0
            if score > best_score:
                best_score, best_term = score, term
        if best_score >= 75:
            scored.append((best_score, str(entry["name"]).casefold(), entry, best_term))
    scored.sort(key=lambda item: (-item[0], item[1]))
    bounded = max(1, min(limit, _MAX_SEARCH_RESULTS))
    return [skill_card(entry, matched_term=term) for _, _, entry, term in scored[:bounded]]


def _as_classified(match: dict[str, Any], context: str) -> dict[str, Any]:
    by_name, _ = _entry_indexes()
    entry = by_name[normalize_taxonomy_key(str(match["name"]))]
    return {
        "skill_id": skill_id_for(entry),
        "canonical_name": entry["name"],
        "matched_term": match.get("matched_term") or entry["name"],
        "confidence": float(match.get("confidence", 1.0)),
        "context": context,
        "category": entry.get("category") or "Uncategorized",
        "subcategory": entry.get("subcategory"),
    }


def _excluded_text(text: str) -> str:
    rows = []
    pattern = re.compile(r"\b(?:exclude|excluded|without|must not have|no experience with)\b", re.I)
    for line in text.splitlines():
        if pattern.search(line):
            rows.append(line)
    return "\n".join(rows)


def _cue_text(text: str, cues: str) -> str:
    pattern = re.compile(cues, re.I)
    clauses = re.split(r"(?<=[.;])\s+|\n+", text)
    return "\n".join(clause for clause in clauses if pattern.search(clause))


def extract_requirement_intelligence(text: str, include_unknown_terms: bool = False) -> dict[str, Any]:
    required_text = extract_required_skills_text(text) or _cue_text(
        text, r"\b(?:must[ -]?have|required|mandatory|need(?:ed)?|strong experience)\b",
    )
    preferred_text = extract_preferred_skills_text(text) or _cue_text(
        text, r"\b(?:preferred|nice[ -]?to[ -]?have|good[ -]?to[ -]?have|bonus|plus)\b",
    )
    excluded_text = _excluded_text(text)
    sections = {
        "required": extract_skills(required_text) if required_text else [],
        "preferred": extract_skills(preferred_text) if preferred_text else [],
        "excluded": extract_skills(excluded_text) if excluded_text else [],
        "mentioned": extract_skills(text),
    }
    classified: dict[str, list[dict[str, Any]]] = {key: [] for key in _CONTEXT_ORDER}
    claimed: set[str] = set()
    for context in _CONTEXT_ORDER:
        for match in sections[context]:
            row = _as_classified(match, context)
            if row["skill_id"] in claimed:
                continue
            claimed.add(row["skill_id"])
            classified[context].append(row)
        classified[context].sort(key=lambda item: item["canonical_name"].casefold())

    stack: dict[str, list[dict[str, Any]]] = {}
    for context in _CONTEXT_ORDER:
        for row in classified[context]:
            category_key = normalize_taxonomy_key(row["category"]).replace(" ", "_") or "uncategorized"
            stack.setdefault(category_key, []).append(row)
    stack = {key: stack[key] for key in sorted(stack)}

    # Arbitrary page prose must never enter the controlled learning queue.
    # Unknown terms are only returned by explicit batch resolution today.
    unknown_terms: list[str] = []
    if include_unknown_terms:
        unknown_terms = []
    return {
        "result_version": "hermes_requirement_skill_intelligence_v1",
        "taxonomy_version": taxonomy_revision(),
        "skills": classified,
        "stack": stack,
        "unknown_terms": unknown_terms,
    }
