import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.runtime.db import cursor

# Arbitrary constant identifying this specific lock's purpose (any bigint
# works -- Postgres advisory locks are just a namespace of integers the
# application assigns meaning to itself).
_SKILLS_WRITE_LOCK_KEY = 892310475


TAXONOMY_DIR = Path(__file__).resolve().parent

CANONICAL_SKILLS_PATH = TAXONOMY_DIR / "canonical_skills.json"
# skills.json used to be a second, separately-maintained copy of this same
# data -- extract_skills() (the actual required/preferred-skill matcher for
# parsed emails) read skills.json, while normalize_skill() and the
# /taxonomy/skills/canonical endpoint read canonical_skills.json. The two
# had drifted into near-duplicates of each other and neither was ever
# expanded past ~35 generic software-engineering terms, so IT-staffing
# postings (SAP, Amazon Connect, TIBCO, ...) matched almost nothing no
# matter which file a given code path happened to read. Retired skills.json
# in favor of canonical_skills.json as the single source of truth for both
# paths; the name is kept as an alias so load_skills_taxonomy()'s existing
# callers (the /taxonomy/skills endpoint, the LLM fallback's taxonomy hint)
# don't need to change.
SKILLS_TAXONOMY_PATH = CANONICAL_SKILLS_PATH
SKILL_ALIASES_PATH = TAXONOMY_DIR / "skill_aliases.json"
JOB_TITLES_PATH = TAXONOMY_DIR / "job_titles.json"
TITLE_ALIASES_PATH = TAXONOMY_DIR / "title_aliases.json"


def normalize_taxonomy_key(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.lower().strip()
    normalized = re.sub(r"[^a-z0-9+#.]+", " ", lowered)
    return " ".join(normalized.split())


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clear_taxonomy_cache() -> None:
    """Busts every lru_cache below so a taxonomy file edit takes effect on
    the very next request, in the same running process -- no redeploy.
    The one caller today is approving a taxonomy candidate (HERMES-900,
    app/understanding/taxonomy/candidates.py), which writes the approved
    term straight into canonical_skills.json on disk right before calling
    this.
    """
    load_skills_taxonomy.cache_clear()
    load_canonical_skills_taxonomy.cache_clear()
    load_skill_aliases_taxonomy.cache_clear()
    load_job_titles_taxonomy.cache_clear()
    load_title_aliases_taxonomy.cache_clear()
    build_skill_alias_index.cache_clear()
    build_title_alias_index.cache_clear()


def add_canonical_skill(
    name: str,
    category: str = "Tool/Technology",
    skill_type: str = "tool",
    aliases: list[str] | None = None,
) -> None:
    """Appends a human-approved taxonomy candidate to canonical_skills.json
    and immediately busts the cache so extract_skills() picks it up
    without a redeploy. Refuses a name that's already present (by
    normalized key) rather than writing a duplicate entry.

    The read-modify-write of the JSON file is wrapped in a Postgres
    transaction-scoped advisory lock: two approvals landing at the same
    moment (two admins, or one admin double-clicking) would otherwise
    both read the file before either had written it back, and the second
    write silently discards the first. pg_advisory_xact_lock releases on
    its own when this function's transaction ends, so there is no
    matching unlock call to forget.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(CANONICAL_SKILLS_PATH.read_text(encoding="utf-8"))
        existing_keys = {normalize_taxonomy_key(entry.get("name")) for entry in data["skills"]}

        if normalize_taxonomy_key(name) in existing_keys:
            clear_taxonomy_cache()
            return

        data["skills"].append(
            {
                "name": name,
                "category": category,
                "skill_type": skill_type,
                "aliases": aliases or [],
                "related_skills": [],
                "confidence": "medium",
                "source": "taxonomy_candidate_approved",
            }
        )
        CANONICAL_SKILLS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()


@lru_cache(maxsize=1)
def load_skills_taxonomy() -> dict[str, Any]:
    return _load_json(SKILLS_TAXONOMY_PATH)


@lru_cache(maxsize=1)
def load_canonical_skills_taxonomy() -> dict[str, Any]:
    return _load_json(CANONICAL_SKILLS_PATH)


@lru_cache(maxsize=1)
def load_skill_aliases_taxonomy() -> dict[str, Any]:
    return _load_json(SKILL_ALIASES_PATH)


@lru_cache(maxsize=1)
def load_job_titles_taxonomy() -> dict[str, Any]:
    return _load_json(JOB_TITLES_PATH)


@lru_cache(maxsize=1)
def load_title_aliases_taxonomy() -> dict[str, Any]:
    return _load_json(TITLE_ALIASES_PATH)


def get_skill_entries() -> list[dict[str, Any]]:
    taxonomy = load_skills_taxonomy()
    return taxonomy.get("skills", [])


def get_taxonomy_version() -> str:
    taxonomy = load_skills_taxonomy()
    return taxonomy.get("version", "unknown")


def get_canonical_skill_entries() -> list[dict[str, Any]]:
    taxonomy = load_canonical_skills_taxonomy()
    return taxonomy.get("skills", [])


def get_skill_alias_entries() -> list[dict[str, Any]]:
    taxonomy = load_skill_aliases_taxonomy()
    return taxonomy.get("aliases", [])


def get_job_title_entries() -> list[dict[str, Any]]:
    taxonomy = load_job_titles_taxonomy()
    return taxonomy.get("titles", [])


def get_title_alias_entries() -> list[dict[str, Any]]:
    taxonomy = load_title_aliases_taxonomy()
    return taxonomy.get("aliases", [])


def get_canonical_skill_names() -> list[str]:
    return [
        entry["name"]
        for entry in get_skill_entries()
        if entry.get("name")
    ]


def get_canonical_taxonomy_skill_names() -> list[str]:
    return [
        entry["name"]
        for entry in get_canonical_skill_entries()
        if entry.get("name")
    ]


def get_canonical_job_titles() -> list[str]:
    return [
        entry["title"]
        for entry in get_job_title_entries()
        if entry.get("title")
    ]


@lru_cache(maxsize=1)
def build_skill_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}

    for entry in get_canonical_skill_entries():
        name = entry.get("name")
        if not name:
            continue

        canonical_key = normalize_taxonomy_key(name)
        index[canonical_key] = name

        for alias in entry.get("aliases", []):
            alias_key = normalize_taxonomy_key(alias)
            if alias_key:
                index[alias_key] = name

    for entry in get_skill_alias_entries():
        alias = entry.get("alias")
        canonical = entry.get("canonical_skill")
        alias_key = normalize_taxonomy_key(alias)
        if alias_key and canonical:
            index[alias_key] = canonical

    return index


@lru_cache(maxsize=1)
def build_title_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}

    for entry in get_job_title_entries():
        title = entry.get("title")
        if not title:
            continue

        canonical_key = normalize_taxonomy_key(title)
        index[canonical_key] = title

        for alias in entry.get("aliases", []):
            alias_key = normalize_taxonomy_key(alias)
            if alias_key:
                index[alias_key] = title

    for entry in get_title_alias_entries():
        alias = entry.get("alias")
        canonical = entry.get("canonical_title")
        alias_key = normalize_taxonomy_key(alias)
        if alias_key and canonical:
            index[alias_key] = canonical

    return index
