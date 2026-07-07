import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


TAXONOMY_DIR = Path(__file__).resolve().parent

SKILLS_TAXONOMY_PATH = TAXONOMY_DIR / "skills.json"
CANONICAL_SKILLS_PATH = TAXONOMY_DIR / "canonical_skills.json"
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
