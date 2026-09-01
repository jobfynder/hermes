import json
import os
import re
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.runtime.db import cursor
from app.understanding.taxonomy.title_family_classifier import compute_related_job_titles


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


def _loose_key(value: str | None) -> str:
    """A stricter, punctuation-blind key used only for duplicate
    DETECTION (never for storage or display) -- normalize_taxonomy_key
    deliberately keeps '.', '+', '#' because they're load-bearing for
    real distinct names (".NET" vs "NET", "C++" vs "C"), which also
    means it treats "Node.js" and "NodeJS" as two different keys even
    though they're the same skill. This collapses ALL punctuation and
    spacing, so those collide here without changing normalize_taxonomy_key's
    behavior (and every alias/candidate-matching path built on it)
    anywhere else.
    """
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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
    without a redeploy. Refuses a name already covered by an existing
    entry -- by its own normalized name, by any of its aliases, by
    skill_aliases.json, or by a loose punctuation-blind match ("NodeJS"
    against an existing "Node.js") -- rather than writing a semantic
    duplicate. The original check only compared against other entries'
    own `name` field, which let an approval slip through for a term that
    was already recognized as an ALIAS of something else -- two entries
    for the same real skill, invisible to exact-key dedup because the
    new one's key never collided with anyone's canonical name, only
    with an alias.

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
        new_key = normalize_taxonomy_key(name)
        new_loose_key = _loose_key(name)
        already_known = (
            new_key in build_skill_alias_index()
            or (new_loose_key and new_loose_key in build_loose_skill_key_index())
        )

        if already_known:
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


def update_canonical_skill(
    current_name: str,
    new_name: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Same pattern as update_canonical_job_title, for canonical_skills.
    json -- rename a skill (typo, casing) or reclassify its category, in
    place, live immediately. A rename that would collide (by normalized
    key, or by loose punctuation-blind key) with a DIFFERENT existing
    skill is refused; the old name is kept as an alias so a posting
    still using it keeps matching.

    Same case/punctuation-only-rename fix as update_canonical_job_title:
    a rename with the same normalized key ("react js" -> "React JS",
    just casing) now still writes the corrected text -- previously it
    silently no-opped while still reporting updated=True.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
        current_key = normalize_taxonomy_key(current_name)

        entry = next(
            (e for e in data["skills"] if normalize_taxonomy_key(e.get("name")) == current_key),
            None,
        )
        if entry is None:
            return {"updated": False, "reason": "skill_not_found"}

        if new_name and new_name != entry["name"]:
            new_key = normalize_taxonomy_key(new_name)
            new_loose_key = _loose_key(new_name)

            if new_key != current_key:
                collision = any(
                    other is not entry
                    and (
                        normalize_taxonomy_key(other.get("name")) == new_key
                        or (new_loose_key and _loose_key(other.get("name")) == new_loose_key)
                    )
                    for other in data["skills"]
                )
                if collision:
                    return {"updated": False, "reason": "duplicate_skill"}

                aliases = entry.setdefault("aliases", [])
                if entry["name"] not in aliases:
                    aliases.append(entry["name"])

            entry["name"] = new_name

        if category is not None:
            entry["category"] = category

        _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()

    return {"updated": True, "name": entry["name"]}


def delete_canonical_skill(name: str) -> dict[str, Any]:
    """Permanently removes a canonical skill -- for a genuinely bad entry
    (a parser artifact that got approved by mistake, an exact duplicate
    of a differently-spelled skill that should have been an alias
    instead). Unlike a rename, this does NOT preserve the old name as an
    alias -- the whole point is that this skill should no longer match
    anything. Missing skill is reported, not raised, same as the other
    taxonomy mutators here.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
        key = normalize_taxonomy_key(name)
        remaining = [e for e in data["skills"] if normalize_taxonomy_key(e.get("name")) != key]

        if len(remaining) == len(data["skills"]):
            return {"deleted": False, "reason": "skill_not_found"}

        data["skills"] = remaining
        _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()

    return {"deleted": True, "name": name}


def bulk_delete_skills(names: list[str]) -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
        wanted_keys = {normalize_taxonomy_key(n) for n in names}

        deleted_names = [e["name"] for e in data["skills"] if normalize_taxonomy_key(e.get("name")) in wanted_keys]
        data["skills"] = [e for e in data["skills"] if normalize_taxonomy_key(e.get("name")) not in wanted_keys]

        if deleted_names:
            _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {"deleted_count": len(deleted_names), "deleted_names": deleted_names}


def bulk_set_skill_category(names: list[str], category: str) -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SKILLS_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("canonical_skills.json").read_text(encoding="utf-8"))
        wanted_keys = {normalize_taxonomy_key(n) for n in names}

        updated_names: list[str] = []
        for entry in data["skills"]:
            if normalize_taxonomy_key(entry.get("name")) in wanted_keys:
                entry["category"] = category
                updated_names.append(entry["name"])

        if updated_names:
            _writable_taxonomy_path("canonical_skills.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {"updated_count": len(updated_names), "updated_names": updated_names}


def delete_canonical_job_title(title: str) -> dict[str, Any]:
    """Same reasoning as delete_canonical_skill, for job_titles.json."""
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        key = normalize_taxonomy_key(title)
        remaining = [e for e in data["titles"] if normalize_taxonomy_key(e.get("title")) != key]

        if len(remaining) == len(data["titles"]):
            return {"deleted": False, "reason": "job_title_not_found"}

        data["titles"] = remaining
        _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()

    return {"deleted": True, "title": title}


def bulk_delete_job_titles(titles: list[str]) -> dict[str, Any]:
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        wanted_keys = {normalize_taxonomy_key(t) for t in titles}

        deleted_titles = [e["title"] for e in data["titles"] if normalize_taxonomy_key(e.get("title")) in wanted_keys]
        data["titles"] = [e for e in data["titles"] if normalize_taxonomy_key(e.get("title")) not in wanted_keys]

        if deleted_titles:
            _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {"deleted_count": len(deleted_titles), "deleted_titles": deleted_titles}


def add_canonical_job_title(
    title: str,
    family: str = "Unclassified",
    seniority: str = "unspecified",
    aliases: list[str] | None = None,
) -> None:
    """Same pattern as add_canonical_skill above, for job_titles.json --
    same advisory lock (a distinct key so a skill approval and a title
    approval never block each other), same live-immediately-no-redeploy
    cache bust. Duplicate check now covers aliases and a loose
    punctuation-blind key too, same reasoning as add_canonical_skill's
    docstring above -- the old normalized-name-only check missed a term
    that was already recognized as an ALIAS of a different title.

    related_titles is always computed deterministically on add (see
    compute_related_job_titles) -- token overlap against every other
    title already in the taxonomy, no LLM, so it's free to run on every
    single approval.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        new_key = normalize_taxonomy_key(title)
        new_loose_key = _loose_key(title)
        already_known = (
            new_key in build_title_alias_index()
            or (new_loose_key and new_loose_key in build_loose_title_key_index())
        )

        if already_known:
            clear_taxonomy_cache()
            return

        related_titles = compute_related_job_titles(title, family, data["titles"])

        data["titles"].append(
            {
                "title": title,
                "family": family,
                "seniority": seniority,
                "aliases": aliases or [],
                "related_titles": related_titles,
                "confidence": "medium",
                "source": "taxonomy_candidate_approved",
            }
        )
        _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()


def update_canonical_job_title(
    current_title: str,
    new_title: str | None = None,
    family: str | None = None,
    seniority: str | None = None,
) -> dict[str, Any]:
    """Lets a reviewer fix a canonical job title in place -- rename a
    typo, reclassify its family/seniority (the common case: an approved
    title landing as family="Unclassified" and needing a real
    classification later) -- same live-immediately-no-redeploy pattern
    as add_canonical_job_title.

    A rename is refused if it would collide (by normalized key, or by
    the same loose punctuation-blind key add_canonical_job_title now
    also checks) with a DIFFERENT existing title -- an edit must never
    quietly merge two distinct titles into one by accident. When the
    new text is a genuinely different entity (its normalized key
    differs), the title being renamed FROM is kept as an alias, so an
    email that still uses the old wording is still recognized rather
    than starting to look like a new unknown term again.

    BUG FIXED HERE: a rename that only changes casing/punctuation/
    whitespace -- "java developer" -> "Java Developer" -- has the SAME
    normalized key as before, so the old code's `if new_key !=
    current_key` guard skipped the whole rename branch and never wrote
    the corrected text, while still returning updated=True. The caller
    (and the reviewer) saw a "successful" save that silently did
    nothing and the row reverted to its old text on reload. Fixed by
    always writing entry["title"] = new_title whenever the literal text
    actually differs, and only running the collision-check/alias-
    preservation dance when it's actually a different entity (different
    normalized key) that needs it.

    related_titles is recomputed deterministically (see
    compute_related_job_titles) whenever the title text or family
    changes, since either can change which other titles are actually
    related.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        current_key = normalize_taxonomy_key(current_title)

        entry = next(
            (e for e in data["titles"] if normalize_taxonomy_key(e.get("title")) == current_key),
            None,
        )
        if entry is None:
            return {"updated": False, "reason": "job_title_not_found"}

        title_or_family_changed = False

        if new_title and new_title != entry["title"]:
            new_key = normalize_taxonomy_key(new_title)
            new_loose_key = _loose_key(new_title)

            if new_key != current_key:
                collision = any(
                    other is not entry
                    and (
                        normalize_taxonomy_key(other.get("title")) == new_key
                        or (new_loose_key and _loose_key(other.get("title")) == new_loose_key)
                    )
                    for other in data["titles"]
                )
                if collision:
                    return {"updated": False, "reason": "duplicate_title"}

                aliases = entry.setdefault("aliases", [])
                if entry["title"] not in aliases:
                    aliases.append(entry["title"])

            entry["title"] = new_title
            title_or_family_changed = True

        if family is not None and family != entry.get("family"):
            entry["family"] = family
            title_or_family_changed = True

        if seniority is not None:
            entry["seniority"] = seniority

        if title_or_family_changed:
            entry["related_titles"] = compute_related_job_titles(
                entry["title"], entry.get("family"), [e for e in data["titles"] if e is not entry]
            )

        _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        clear_taxonomy_cache()

    return {"updated": True, "title": entry["title"]}


def bulk_set_job_title_family(titles: list[str], family: str) -> dict[str, Any]:
    """Reclassifies several titles' family in one write -- the common
    maintenance task after a batch of approvals all landed as
    family="Unclassified" (add_canonical_job_title's default) and need
    sorting into real families, without a human editing each one alone.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        wanted_keys = {normalize_taxonomy_key(t) for t in titles}

        updated_titles: list[str] = []
        for entry in data["titles"]:
            if normalize_taxonomy_key(entry.get("title")) in wanted_keys:
                entry["family"] = family
                updated_titles.append(entry["title"])

        if updated_titles:
            _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {"updated_count": len(updated_titles), "updated_titles": updated_titles}


def bulk_apply_job_title_families(family_by_title: dict[str, str]) -> dict[str, Any]:
    """Like bulk_set_job_title_family, but each title gets its OWN family
    rather than one family applied to all of them -- what a batch
    auto-classification pass needs (app/understanding/taxonomy/
    title_family_classifier.py), where different titles land in
    different families in the same run.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        wanted = {normalize_taxonomy_key(t): family for t, family in family_by_title.items()}

        updated_titles: list[str] = []
        for entry in data["titles"]:
            key = normalize_taxonomy_key(entry.get("title"))
            if key in wanted:
                entry["family"] = wanted[key]
                updated_titles.append(entry["title"])

        if updated_titles:
            _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {"updated_count": len(updated_titles), "updated_titles": updated_titles}


def bulk_backfill_related_titles() -> dict[str, Any]:
    """One-shot pass over every canonical job title with an EMPTY
    related_titles list, filling it in deterministically (see
    compute_related_job_titles) against the full current taxonomy. For
    clearing the backlog of older entries added before related_titles
    was computed on approval, the same shape as
    auto_classify_unclassified_job_titles's backlog-clearing role for
    family. Never touches a title that already has at least one related
    title -- a reviewer may have hand-picked those, and re-deriving them
    from scratch on every backfill run would silently discard that.
    """
    with cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TITLES_WRITE_LOCK_KEY,))

        data = json.loads(_writable_taxonomy_path("job_titles.json").read_text(encoding="utf-8"))
        titles = data["titles"]

        updated_titles: list[str] = []
        for entry in titles:
            if entry.get("related_titles"):
                continue
            related = compute_related_job_titles(
                entry.get("title", ""), entry.get("family"), [e for e in titles if e is not entry]
            )
            if related:
                entry["related_titles"] = related
                updated_titles.append(entry["title"])

        if updated_titles:
            _writable_taxonomy_path("job_titles.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            clear_taxonomy_cache()

    return {
        "checked_count": len(titles),
        "backfilled_count": len(updated_titles),
        "backfilled_titles": updated_titles,
    }


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


def build_loose_skill_key_index() -> dict[str, str]:
    """Same coverage as build_skill_alias_index (every canonical name,
    every skill's own aliases, every skill_aliases.json entry) but keyed
    by _loose_key instead of normalize_taxonomy_key -- so "Node.js" and
    "NodeJS" collide here even though they're distinct entries in the
    exact-key index. Used only to decide "is this basically already a
    known skill" (duplicate prevention on approval, candidate detection),
    never to resolve a term to its canonical spelling.
    """
    return {_loose_key(key): canonical for key, canonical in build_skill_alias_index().items() if _loose_key(key)}


def build_loose_title_key_index() -> dict[str, str]:
    """Loose-key counterpart to build_title_alias_index, same reasoning
    as build_loose_skill_key_index above.
    """
    return {_loose_key(key): canonical for key, canonical in build_title_alias_index().items() if _loose_key(key)}
