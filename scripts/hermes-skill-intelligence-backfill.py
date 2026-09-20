"""Materialize stable skill IDs and reviewed glossary enrichment.

Safe to run repeatedly. Existing IDs and human-authored enrichment always win.
The one exception is a generic category ("Tool/Technology", "Uncategorized"),
which carries no information and is replaced by the reviewed category.

The runtime taxonomy can be passed explicitly; the checked-in seed is the
default so new deployments begin with stable identities.

Use --dry-run to see what would change without writing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skill_intelligence.enrichment import ENRICHMENT, GENERIC_CATEGORIES
from app.understanding.taxonomy.identity import stable_skill_id


def apply_enrichment(data: dict) -> dict[str, int]:
    """Apply IDs and enrichment in place and return simple counts for reporting.

    Skills are matched by name ignoring case, so "JIRA" and "Jira" receive the same reviewed text.
    """
    by_key = {name.casefold(): row for name, row in ENRICHMENT.items()}
    counts = {"skills": 0, "ids_added": 0, "enriched": 0, "categories_fixed": 0, "missing": 0}
    seen: set[str] = set()
    for skill in data.get("skills", []):
        counts["skills"] += 1
        seen.add(skill["name"].casefold())
        if "skill_id" not in skill:
            skill["skill_id"] = stable_skill_id(skill["name"])
            counts["ids_added"] += 1
        changed = False
        for key, value in by_key.get(skill["name"].casefold(), {}).items():
            if key == "category":
                if skill.get("category", "") in GENERIC_CATEGORIES:
                    skill["category"] = value
                    counts["categories_fixed"] += 1
                continue
            if not skill.get(key):
                skill[key] = value
                changed = True
        if changed:
            counts["enriched"] += 1
        skill.setdefault("status", "active")
    counts["missing"] = len([key for key in by_key if key not in seen])
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app/understanding/taxonomy/canonical_skills.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="report the changes without writing the file")
    args = parser.parse_args()
    raw = args.path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    data = json.loads(raw.decode("utf-8"))
    counts = apply_enrichment(data)
    print(json.dumps(counts))
    if args.dry_run:
        return
    payload = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", newline) + newline
    args.path.write_bytes(payload.encode("utf-8"))


if __name__ == "__main__":
    main()
