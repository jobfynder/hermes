from __future__ import annotations

from typing import Any

from app.runtime.jsonl_store import read_json, runtime_path, write_json

# Approved taxonomy additions live here, on the persistent /hermes-runtime
# volume - NOT in the git-tracked seed files (canonical_skills.json etc).
# This keeps approvals durable across container restarts without needing a
# code deploy for every single approval. Periodically, a maintainer can fold
# this overlay into the seed JSON files via a deliberate commit, the same
# way this project treats 'working state' vs. 'reviewed baseline' elsewhere.


def _overlay_path():
    return runtime_path('taxonomy', 'approved_additions.json')


def load_overlay() -> dict[str, list[dict[str, Any]]]:
    record = read_json(_overlay_path())

    if not record:
        return {
            'canonical_skills': [],
            'skill_aliases': [],
            'job_titles': [],
            'title_aliases': [],
        }

    for key in ('canonical_skills', 'skill_aliases', 'job_titles', 'title_aliases'):
        record.setdefault(key, [])

    return record


def _save_overlay(overlay: dict[str, list[dict[str, Any]]]) -> None:
    write_json(_overlay_path(), overlay)


def add_canonical_skill(name: str) -> None:
    overlay = load_overlay()
    overlay['canonical_skills'].append({'name': name, 'aliases': []})
    _save_overlay(overlay)


def add_skill_alias(alias: str, canonical_skill: str) -> None:
    overlay = load_overlay()
    overlay['skill_aliases'].append({'alias': alias, 'canonical_skill': canonical_skill})
    _save_overlay(overlay)


def add_canonical_job_title(title: str) -> None:
    overlay = load_overlay()
    overlay['job_titles'].append({'title': title, 'aliases': []})
    _save_overlay(overlay)


def add_title_alias(alias: str, canonical_title: str) -> None:
    overlay = load_overlay()
    overlay['title_aliases'].append({'alias': alias, 'canonical_title': canonical_title})
    _save_overlay(overlay)
