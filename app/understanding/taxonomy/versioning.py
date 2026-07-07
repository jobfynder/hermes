from __future__ import annotations

from app.understanding.taxonomy.loader import (
    CANONICAL_SKILLS_PATH,
    JOB_TITLES_PATH,
    SKILL_ALIASES_PATH,
    TITLE_ALIASES_PATH,
    get_canonical_skill_entries,
    get_job_title_entries,
    get_skill_alias_entries,
    get_title_alias_entries,
    load_canonical_skills_taxonomy,
    load_job_titles_taxonomy,
    load_skill_aliases_taxonomy,
    load_title_aliases_taxonomy,
)


SNAPSHOT_NAME = "hermes-400-taxonomy-foundation-v1"


def build_taxonomy_snapshot(validation_status: str = "not_run") -> dict[str, object]:
    canonical_skills = load_canonical_skills_taxonomy()
    skill_aliases = load_skill_aliases_taxonomy()
    job_titles = load_job_titles_taxonomy()
    title_aliases = load_title_aliases_taxonomy()

    return {
        "result_version": "hermes_taxonomy_snapshot_v1",
        "snapshot_name": SNAPSHOT_NAME,
        "taxonomy_versions": {
            "canonical_skills": canonical_skills.get("version", "unknown"),
            "skill_aliases": skill_aliases.get("version", "unknown"),
            "job_titles": job_titles.get("version", "unknown"),
            "title_aliases": title_aliases.get("version", "unknown"),
        },
        "counts": {
            "canonical_skills": len(get_canonical_skill_entries()),
            "skill_aliases": len(get_skill_alias_entries()),
            "job_titles": len(get_job_title_entries()),
            "title_aliases": len(get_title_alias_entries()),
        },
        "source_files": {
            "canonical_skills": str(CANONICAL_SKILLS_PATH.name),
            "skill_aliases": str(SKILL_ALIASES_PATH.name),
            "job_titles": str(JOB_TITLES_PATH.name),
            "title_aliases": str(TITLE_ALIASES_PATH.name),
        },
        "validation_status": validation_status,
    }
