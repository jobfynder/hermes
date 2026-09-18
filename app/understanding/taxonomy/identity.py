from __future__ import annotations

import uuid


SKILL_ID_NAMESPACE = uuid.UUID("b914d5d7-755d-4fb7-a4d9-4669d5879651")


def stable_skill_id(canonical_name: str) -> str:
    """Return the migration-safe ID for a legacy canonical skill name."""
    normalized = " ".join(canonical_name.lower().strip().split())
    return f"skill_{uuid.uuid5(SKILL_ID_NAMESPACE, normalized).hex}"
