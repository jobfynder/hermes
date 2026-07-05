import json
from functools import lru_cache
from pathlib import Path
from typing import Any


TAXONOMY_DIR = Path(__file__).resolve().parent
SKILLS_TAXONOMY_PATH = TAXONOMY_DIR / "skills.json"


@lru_cache(maxsize=1)
def load_skills_taxonomy() -> dict[str, Any]:
    return json.loads(SKILLS_TAXONOMY_PATH.read_text(encoding="utf-8"))


def get_skill_entries() -> list[dict[str, Any]]:
    taxonomy = load_skills_taxonomy()
    return taxonomy.get("skills", [])


def get_taxonomy_version() -> str:
    taxonomy = load_skills_taxonomy()
    return taxonomy.get("version", "unknown")


def get_canonical_skill_names() -> list[str]:
    return [
        entry["name"]
        for entry in get_skill_entries()
        if entry.get("name")
    ]
