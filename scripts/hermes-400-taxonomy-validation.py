#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy.loader import normalize_taxonomy_key
from app.understanding.taxonomy.normalizer import normalize_job_title, normalize_skill

TAXONOMY_DIR = ROOT / "app" / "understanding" / "taxonomy"

FILES = {
    "canonical_skills": TAXONOMY_DIR / "canonical_skills.json",
    "skill_aliases": TAXONOMY_DIR / "skill_aliases.json",
    "job_titles": TAXONOMY_DIR / "job_titles.json",
    "title_aliases": TAXONOMY_DIR / "title_aliases.json",
}


def load_json(name: str) -> dict:
    path = FILES[name]
    if not path.exists():
        raise AssertionError(f"Missing taxonomy file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def unique_keys(values: list[str], label: str) -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []

    for value in values:
        key = normalize_taxonomy_key(value)
        if not key:
            duplicates.append(f"{label}: blank value")
            continue
        if key in seen:
            duplicates.append(f"{label}: duplicate '{value}' conflicts with '{seen[key]}'")
        seen[key] = value

    require(not duplicates, "\n".join(duplicates))


def validate_skills() -> None:
    canonical = load_json("canonical_skills")
    aliases = load_json("skill_aliases")

    require(canonical.get("taxonomy_type") == "canonical_skills", "canonical_skills taxonomy_type is invalid")
    require(aliases.get("taxonomy_type") == "skill_aliases", "skill_aliases taxonomy_type is invalid")
    require(canonical.get("version"), "canonical_skills version is missing")
    require(aliases.get("version"), "skill_aliases version is missing")

    skills = canonical.get("skills", [])
    alias_rows = aliases.get("aliases", [])

    require(isinstance(skills, list) and skills, "canonical skills list is empty")
    require(isinstance(alias_rows, list) and alias_rows, "skill aliases list is empty")

    canonical_names = [entry.get("name", "") for entry in skills]
    unique_keys(canonical_names, "canonical skill")

    canonical_key_to_name = {
        normalize_taxonomy_key(name): name
        for name in canonical_names
    }

    alias_targets_by_key: dict[str, set[str]] = defaultdict(set)

    for entry in skills:
        name = entry.get("name")
        require(name, "canonical skill missing name")
        require(entry.get("category"), f"skill '{name}' missing category")
        require(entry.get("skill_type"), f"skill '{name}' missing skill_type")

        for alias in entry.get("aliases", []):
            alias_key = normalize_taxonomy_key(alias)
            require(alias_key, f"skill '{name}' has blank alias")
            alias_targets_by_key[alias_key].add(name)

        for related in entry.get("related_skills", []):
            related_key = normalize_taxonomy_key(related)
            require(
                related_key in canonical_key_to_name,
                f"skill '{name}' has unknown related skill '{related}'",
            )

    for row in alias_rows:
        alias = row.get("alias")
        target = row.get("canonical_skill")
        require(alias, "skill alias row missing alias")
        require(target, f"skill alias '{alias}' missing canonical_skill")
        require(
            normalize_taxonomy_key(target) in canonical_key_to_name,
            f"skill alias '{alias}' points to unknown canonical skill '{target}'",
        )
        alias_targets_by_key[normalize_taxonomy_key(alias)].add(target)

    conflicts = {
        alias_key: sorted(targets)
        for alias_key, targets in alias_targets_by_key.items()
        if len(targets) > 1
    }
    require(not conflicts, f"Conflicting skill aliases found: {conflicts}")


def validate_titles() -> None:
    titles_taxonomy = load_json("job_titles")
    aliases_taxonomy = load_json("title_aliases")

    require(titles_taxonomy.get("taxonomy_type") == "job_titles", "job_titles taxonomy_type is invalid")
    require(aliases_taxonomy.get("taxonomy_type") == "title_aliases", "title_aliases taxonomy_type is invalid")
    require(titles_taxonomy.get("version"), "job_titles version is missing")
    require(aliases_taxonomy.get("version"), "title_aliases version is missing")

    titles = titles_taxonomy.get("titles", [])
    alias_rows = aliases_taxonomy.get("aliases", [])

    require(isinstance(titles, list) and titles, "job titles list is empty")
    require(isinstance(alias_rows, list) and alias_rows, "title aliases list is empty")

    canonical_titles = [entry.get("title", "") for entry in titles]
    unique_keys(canonical_titles, "canonical job title")

    canonical_key_to_title = {
        normalize_taxonomy_key(title): title
        for title in canonical_titles
    }

    alias_targets_by_key: dict[str, set[str]] = defaultdict(set)

    for entry in titles:
        title = entry.get("title")
        require(title, "job title missing title")
        require(entry.get("family"), f"title '{title}' missing family")

        for alias in entry.get("aliases", []):
            alias_key = normalize_taxonomy_key(alias)
            require(alias_key, f"title '{title}' has blank alias")
            alias_targets_by_key[alias_key].add(title)

    for row in alias_rows:
        alias = row.get("alias")
        target = row.get("canonical_title")
        require(alias, "title alias row missing alias")
        require(target, f"title alias '{alias}' missing canonical_title")
        require(
            normalize_taxonomy_key(target) in canonical_key_to_title,
            f"title alias '{alias}' points to unknown canonical title '{target}'",
        )
        alias_targets_by_key[normalize_taxonomy_key(alias)].add(target)

    conflicts = {
        alias_key: sorted(targets)
        for alias_key, targets in alias_targets_by_key.items()
        if len(targets) > 1
    }
    require(not conflicts, f"Conflicting title aliases found: {conflicts}")


def validate_normalizer_examples() -> None:
    skill_examples = {
        "JS": "JavaScript",
        "reactjs": "React",
        "k8s": "Kubernetes",
        "amazon web services": "AWS",
        "genai": "Generative AI",
    }

    title_examples = {
        "Sr Java Developer": "Senior Java Developer",
        "React UI Developer": "Frontend React Developer",
        "SRE": "Site Reliability Engineer",
        "Bench Sales": "Bench Sales Recruiter",
        "BDM": "Business Development Manager",
    }

    for source, expected in skill_examples.items():
        result = normalize_skill(source)
        require(
            result["normalized"] == expected and result["matched"] is True,
            f"skill normalizer failed for '{source}': {result}",
        )

    for source, expected in title_examples.items():
        result = normalize_job_title(source)
        require(
            result["normalized"] == expected and result["matched"] is True,
            f"title normalizer failed for '{source}': {result}",
        )


def main() -> int:
    print("HERMES-400 taxonomy validation started")

    validate_skills()
    print("OK: skill taxonomy files are valid")

    validate_titles()
    print("OK: title taxonomy files are valid")

    validate_normalizer_examples()
    print("OK: taxonomy normalizer examples passed")

    print("HERMES-400 taxonomy validation PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 taxonomy validation FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
