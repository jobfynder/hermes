"""Hermes -> Jobfynder Core vocabulary normalisation.

Core's POST /hermes/job/create resolves references by EXACT, case-insensitive
name against its own reference tables (jobs.service.ts lookup*): employment
types, experience levels, visa types and states (by full name, not code).
Anything that does not match comes back in Core's unmatchedFields and is
dropped from the job. Before this module Hermes sent "Full-time" (Core has
"Full-Time/Permanent"), "TX" (Core has "Texas"), "H1B" (Core has "H-1B") and
"8+ years" (Core has "Senior Level (6-10 years)"), so every one of those
fields would have been lost.

The tables below are a snapshot of Core's seeded reference data
(prisma/migrations/20251225180000_insert_dropdown_data, 20260121212246_add_job_posting_tables),
version-stamped so drift is visible. Pure functions, no I/O. Values with no
Core equivalent are returned as `dropped` rather than guessed.
"""

from __future__ import annotations

import re
from typing import Any

VOCABULARY_VERSION = "core-seed-2026-01"

EMPLOYMENT_TYPES = {
    "contract": "Contract",
    "contract to hire": "Contract to Hire",
    "full-time": "Full-Time/Permanent",
    "full time": "Full-Time/Permanent",
    "permanent": "Full-Time/Permanent",
    "part-time": "Part-Time",
    "part time": "Part-Time",
    "w2": "W2",
    "c2c": "Corp to Corp(C2C)",
    "corp to corp": "Corp to Corp(C2C)",
    "1099": "1099",
    "freelance": "Freelance",
}

# (years lower bound, Core experience level name). 10+ is Lead: recruiters
# writing "10+ years" mean ten or more.
_EXPERIENCE_LEVELS = [
    (10, "Lead Principal (10+ years)"),
    (6, "Senior Level (6-10 years)"),
    (3, "Mid Level (3-5 years)"),
    (0, "Entry Level (0-2 years)"),
]

VISA_TYPES = {
    "h1b": "H-1B", "h-1b": "H-1B", "h 1b": "H-1B",
    "green card": "Green Card", "gc": "Green Card",
    "us citizen": "US Citizen", "usc": "US Citizen", "citizen": "US Citizen",
    "ead": "EAD", "gc ead": "EAD", "l1": "L1", "opt": "OPT", "cpt": "CPT",
}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {name.lower(): name for name in STATES.values()}

_WORK_MODE_WORDS = re.compile(r"\b(?:fully\s+)?(?:remote|hybrid|on[\s-]?site|onsite)\b", re.IGNORECASE)


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def core_employment_types(raw: str | None, *, basis: str | None = None) -> tuple[list[str], list[str]]:
    """(core names, dropped). `basis` (C2C/W2/1099 from the rate) adds the
    matching engagement type only when the posting states it."""
    names: list[str] = []
    dropped: list[str] = []
    if raw:
        mapped = EMPLOYMENT_TYPES.get(_key(raw))
        (names if mapped else dropped).append(mapped or raw)
    if basis:
        extra = EMPLOYMENT_TYPES.get(_key(basis))
        if extra and extra not in names:
            names.append(extra)
    return names, dropped


def core_experience_level(years: Any) -> str | None:
    try:
        value = float(years)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    for lower, name in _EXPERIENCE_LEVELS:
        if value >= lower:
            return name
    return None


def core_visa_types(raw: str | None) -> tuple[list[str], list[str]]:
    """Core has no 'any visa', 'TN' or 'no sponsorship' entries: those are
    returned as dropped (kept in the job description) instead of guessed."""
    if not raw:
        return [], []
    names: list[str] = []
    dropped: list[str] = []
    for part in re.split(r"[,/;]|\band\b|\bor\b", raw, flags=re.IGNORECASE):
        part = part.strip()
        if not part:
            continue
        mapped = VISA_TYPES.get(_key(part))
        if mapped:
            if mapped not in names:
                names.append(mapped)
        else:
            dropped.append(part)
    return names, dropped


def split_location(raw: str | None) -> dict[str, Any]:
    """'Hybrid - Dallas, TX' / 'Dallas, TX (Remote)' / 'Austin, Texas' ->
    {'city','state'(full name),'work_mode'}. State is the full Core name when
    recognisable, else omitted (a code Core cannot match is worse than none)."""
    text = raw or ""
    result: dict[str, Any] = {}
    mode = _WORK_MODE_WORDS.search(text)
    if mode:
        word = mode.group(0).lower().replace("-", "").replace(" ", "")
        result["work_mode"] = "REMOTE" if "remote" in word else "HYBRID" if "hybrid" in word else "ONSITE"

    cleaned = re.sub(r"\([^)]*\)", " ", text)
    cleaned = _WORK_MODE_WORDS.sub(" ", cleaned)
    parts =[p.strip(" -–—|") for p in cleaned.split(",") if p.strip(" -–—|")]
    if not parts:
        return result

    state_part = parts[-1] if len(parts) > 1 else None
    city_part = parts[0]
    if state_part is None:
        # "Dallas TX" without a comma
        match = re.match(r"^(?P<city>.+?)\s+(?P<st>[A-Z]{2})$", city_part)
        if match and match.group("st") in STATES:
            city_part, state_part = match.group("city"), match.group("st")
    if state_part:
        token = state_part.strip()
        state = STATES.get(token.upper()) if len(token) == 2 else _STATE_BY_NAME.get(token.lower())
        if state:
            result["state"] = state
    if city_part and not (len(city_part) == 2 and city_part.upper() in STATES):
        result["city"] = city_part
    return result
