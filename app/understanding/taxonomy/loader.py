import json
import os
import re
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.runtime.db import cursor


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

# Arbitrary constants identifying each lock's purpose (any bigint works --
# Postgres advisory locks are just a namespace of integers the application
# assigns meaning to itself). Distinct keys so a skill approval and a job
# title approval -- different files -- never block each other.
_SKILLS_WRITE_LOCK_KEY = 892310475
_TITLES_WRITE_LOCK_KEY = 892310476


TAXONOMY_DIR = Path(__file__).resolve().parent

# Where canonical_skills.json/job_titles.json actually get read from and
# written to at runtime -- NOT TAXONOMY_DIR. TAXONOMY_DIR is inside the
# git-tracked source tree, which `docker compose build` recreates fresh
# from git on every deploy; a write there (approving a taxonomy
# candidate, editing a skill description) lives only in that one
# container's filesystem layer and silently vanishes the next time the
# image is rebuilt for anything else. Confirmed the hard way: an entire
# 181-skill description backfill was wiped by the next unrelated deploy.
# _hermes-runtime is the persistent volume already mounted into both
# hermes-api and hermes-graph-consumer (docker-compose.yml) for exactly
# this kind of runtime-mutable state (see HERMES_ACCESS_CONTROL_FILE).
# On first use in a given environment, the runtime copy is seeded from
# the git-tracked baseline in TAXONOMY_DIR; every write after that goes
# straight to the runtime copy, which a rebuild never touches.
_TAXONOMY_RUNTIME_DIR = Path(os.getenv("HERMES_TAXONOMY_RUNTIME_DIR", "/hermes-runtime/taxonomy"))


@lru_cache(maxsize=None)
def _writable_taxonomy_path(filename: str) -> Path:
    seed_path = TAXONOMY_DIR / filename
    runtime_path = _TAXONOMY_RUNTIME_DIR / filename

    if not runtime_path.exists():
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_path, runtime_path)

    return runtime_path


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


# hermes-api and hermes-graph-consumer are two separate OS processes,
# each with its own independent in-memory cache -- a plain @lru_cache
# only ever gets busted in whichever process actually calls
# clear_taxonomy_cache() (approvals only ever happen through hermes-api).
# Real incident: hermes-graph-consumer -- the process that actually
# parses live incoming mail -- kept its stale copy of canonical_skills.
# json/job_titles.json for its entire uptime, so a term approved through
# the review UI could get flagged as "unknown" again by the very next
# email that mentioned it, silently re-queuing work a human had just
# finished. Keyed on the file's own mtime instead of a plain forever-
# cache: any process, on its own next read, notices the file changed
# (written by ANY process, since both read the same file on the shared
# runtime volume -- app/understanding/taxonomy/loader.py's
# _writable_taxonomy_path) and reloads -- no cross-process messaging
# needed, just a stat() call, cheap enough to do on every access.
_mtime_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _load_json_cached_by_mtime(path: Path) -> dict[str, Any]:
    key = str(path)
    mtime = path.stat().st_mtime
    cached = _mtime_cache.get(key)

    if cached is not None and cached[0] == mtime:
        return cached[1]

    data = _load_json(path)
    _mtime_cache[key] = (mtime, data)
    return data


def clear_taxonomy_cache() -> None:
    """Evicts the mtime-cache entries for the two files taxonomy
    candidate approval writes to, in this process -- immediate effect
    here regardless of filesystem mtime-resolution granularity, on top
    of the mtime check above already making every *other* process (this
    one's own next read included, belt and suspenders) pick up the
    change on its own. The one caller today is approving a taxonomy
    candidate (HERMES-900, app/understanding/taxonomy/candidates.py),
    which writes the approved term straight into canonical_skills.json/
    job_titles.json on disk right before calling this.
    """
    load_skill_aliases_taxonomy.cache_clear()
    load_title_aliases_taxonomy.cache_clear()
    _mtime_cache.pop(str(_writable_taxonomy_path("canonical_skills.json")), None)
    _mtime_cache.pop(str(_writable_taxonomy_path("job_titles.json")), None)


def add_canonical_skill(
    name: str,
    category: str = "Tool/Technology",
    skill_type: str = "tool",
    aliases: list[str] | None = None,
    description: str | None = None,
) -> None:
    """Appends a human-approved taxonomy candidate to canonical_skills.json
    and immediately busts the cache so extract_skills() picks it up
    without a redeploy. Refuses a name that's already present (by
    normalized key) rather than writing a duplicate entry.

    description is a one-sentence, recruiter-facing definition (see
    app/understanding/taxonomy/descriptions.py) -- optional here because
    the caller may not have one yet at approval time and fill it in via
    set_skill_description() moments later once the LLM call returns.

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

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
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
                "description": description,
                "description_source": "ai_generated" if description else None,
            }
        )
        _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()


class SkillDescriptionLocked(Exception):
    """Raised when an AI-generated write tries to overwrite a
    human-edited description -- see set_skill_description. Distinct from
    returning False (that means "no such skill"; this means "the skill
    exists but a human already made this call, so no")."""


def set_skill_description(
    name: str,
    description: str,
    source: str = "ai_generated",
    edited_by: str | None = None,
) -> bool:
    """Fills in or overwrites a canonical skill's recruiter-facing
    description in place -- used by the one-time backfill script
    (scripts/hermes-taxonomy-generate-descriptions.py), approval-time
    auto-generation, and the reviewer inline-edit endpoint (both in
    app/understanding/taxonomy/candidates.py). Returns False if no skill
    with this normalized name exists (nothing to update).

    source is stamped on the entry as description_source so the taxonomy
    browse page can show "AI" vs "edited" -- and, more importantly, is
    what a human edit is protected by: once a description carries
    source="human_edited", a caller passing source="ai_generated" (i.e.
    an automated regeneration, not a human hitting Save) raises
    SkillDescriptionLocked instead of silently clobbering the edit. A
    human calling this again (source="human_edited") always wins,
    including over another human's earlier edit -- last save wins is the
    expected behavior for a shared admin field.

    Same advisory lock as add_canonical_skill, since this is the same
    read-modify-write of the same file.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
        key = normalize_taxonomy_key(name)

        for entry in data["skills"]:
            if normalize_taxonomy_key(entry.get("name")) == key:
                if source == "ai_generated" and entry.get("description_source") == "human_edited":
                    raise SkillDescriptionLocked(name)

                entry["description"] = description
                entry["description_source"] = source
                if source == "human_edited":
                    entry["description_edited_by"] = edited_by
                    entry["description_edited_at"] = _utc_now_iso()

                _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                clear_taxonomy_cache()
                return True

        return False


def add_canonical_job_title(
    title: str,
    family: str = "Unclassified",
    seniority: str = "unspecified",
    aliases: list[str] | None = None,
) -> None:
    """Same pattern as add_canonical_skill above, for job_titles.json --
    same advisory lock (a distinct key so a skill approval and a title
    approval never block each other), same live-immediately-no-redeploy
    cache bust, same refuse-a-duplicate-by-normalized-key behavior.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        existing_keys = {normalize_taxonomy_key(entry.get("title")) for entry in data["titles"]}

        if normalize_taxonomy_key(title) in existing_keys:
            clear_taxonomy_cache()
            return

        data["titles"].append(
            {
                "title": title,
                "family": family,
                "seniority": seniority,
                "aliases": aliases or [],
                "related_titles": [],
                "confidence": "medium",
                "source": "taxonomy_candidate_approved",
            }
        )
        _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()


def load_skills_taxonomy() -> dict[str, Any]:
    return _load_json_cached_by_mtime(_writable_taxonomy_path("canonical_skills.json"))


def load_canonical_skills_taxonomy() -> dict[str, Any]:
    return _load_json_cached_by_mtime(_writable_taxonomy_path("canonical_skills.json"))


@lru_cache(maxsize=1)
def load_skill_aliases_taxonomy() -> dict[str, Any]:
    return _load_json(SKILL_ALIASES_PATH)


def load_job_titles_taxonomy() -> dict[str, Any]:
    return _load_json_cached_by_mtime(_writable_taxonomy_path("job_titles.json"))


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


def build_skill_alias_index() -> dict[str, str]:
    """Deliberately uncached, unlike the load_* functions it's built from
    -- those already handle staleness (mtime-checked), and reconstructing
    this dict from their result is a rebuild over a few hundred entries,
    microseconds, not worth a second caching layer that would need its
    own invalidation story on top of theirs.
    """
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
