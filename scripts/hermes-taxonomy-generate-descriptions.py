"""One-time backfill: generates a recruiter-facing description for every
canonical skill that doesn't have one yet. Safe to re-run -- only fills
missing descriptions, never overwrites an existing one. Run against
production directly (docker exec hermes-api python3 scripts/hermes-
taxonomy-generate-descriptions.py); each skill is written and cache-
busted individually via set_skill_description, so a failure partway
through leaves everything already written intact.
"""

import sys
import time

from app.prompt_runtime.service import litellm_configured
from app.understanding.taxonomy.descriptions import generate_skill_description
from app.understanding.taxonomy.loader import get_canonical_skill_entries, set_skill_description


def main() -> None:
    if not litellm_configured():
        print("LITELLM_API_KEY is not set -- nothing to do.")
        sys.exit(1)

    entries = get_canonical_skill_entries()
    missing = [e for e in entries if not e.get("description")]

    print(f"{len(entries)} total skills, {len(missing)} missing a description")

    filled = 0
    failed = 0

    for entry in missing:
        name = entry["name"]
        category = entry.get("category")

        description = generate_skill_description(name, category=category)

        if not description:
            print(f"FAILED (no description returned): {name}")
            failed += 1
            continue

        ok = set_skill_description(name, description)
        if ok:
            print(f"OK: {name} -> {description}")
            filled += 1
        else:
            print(f"FAILED (skill not found on write-back): {name}")
            failed += 1

        # Gentle pacing -- this is a one-time admin script, not the live
        # request path; no need to hammer the gateway.
        time.sleep(0.2)

    print(f"\nfilled={filled} failed={failed}")


if __name__ == "__main__":
    main()
