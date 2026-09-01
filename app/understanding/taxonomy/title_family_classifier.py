"""Deterministic-first family classification for canonical job titles.

Most IT staffing job titles follow extremely repetitive patterns
("<Tech> Developer", "SAP <Module> Consultant", "<Domain> Business
Analyst") that a small keyword ruleset classifies correctly without ever
needing a model call. LLM is only a fallback for the genuine minority a
keyword can't confidently place, going through the same LiteLLM gateway
every other Hermes AI capability uses (app/prompt_runtime/service.py),
the same pattern as generate_skill_description
(app/understanding/taxonomy/descriptions.py). Kept strictly best-effort:
a classification failure (no LiteLLM key, a bad response) never raises,
it just leaves the title exactly as unclassified as it already was for
a human to finish.
"""

from __future__ import annotations

import os
import re

from app.prompt_runtime.models import PromptRenderedMessage
from app.prompt_runtime.service import _call_litellm_with_model, litellm_configured

# Checked in order -- more specific families first, so e.g. "AI Engineer"
# is claimed by AI Engineering before the generic "engineer" catch-all
# under Software Engineering gets a chance at it. Each keyword is matched
# as a substring against the normalized (lowercased, punctuation-
# collapsed, space-padded) title -- extend this list as new recurring
# patterns show up in the review queue, the same way the taxonomy
# candidate queues themselves grow.
_FAMILY_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    (
        "AI Engineering",
        ["ai engineer", "machine learning", "ml engineer", "genai", "gen ai", "agentic ai", "llm engineer", "nlp engineer"],
    ),
    (
        "Data",
        ["data engineer", "data analyst", "data scientist", " etl ", "data warehouse", "business intelligence",
         "bi developer", "bi analyst", "analytics engineer", "data architect"],
    ),
    (
        "Quality Engineering",
        [" qa ", "quality engineer", "quality analyst", "quality assurance", "test engineer", "sdet",
         "automation tester", "qa lead"],
    ),
    (
        "Infrastructure",
        ["network engineer", "systems administrator", "sysadmin", "cloud engineer", "devops", "site reliability",
         " sre ", "infrastructure", "platform engineer", "cloud architect"],
    ),
    ("Architecture", ["architect"]),
    ("Recruiting", ["recruiter", "talent acquisition", "sourcer", "bench sales", " staffing "]),
    ("Sales", [" sales ", "account executive", "business development"]),
    ("Business Analysis", ["business analyst", "systems analyst", " ba "]),
    ("Project Management", ["project manager", "program manager", "scrum master", "delivery manager", " pmo "]),
    ("Product", ["product manager", "product owner"]),
    ("Design", ["ux designer", "ui designer", "graphic designer", "product designer", "visual designer"]),
    ("ITSM", ["service desk", "help desk", " itsm ", "it support", "desktop support"]),
    ("HCM", [" hcm ", "human capital", "workday hcm", " hris "]),
    ("ERP", [" sap ", "sap ", " erp ", "oracle ebs", "peoplesoft", "netsuite", "d365", "dynamics 365"]),
    (
        "Software Engineering",
        ["developer", "engineer", "programmer", "full stack", "backend", "front end", "frontend", "software"],
    ),
]


def _normalize(title: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()} "


def classify_family_deterministically(title: str) -> str | None:
    normalized = _normalize(title)
    for family, keywords in _FAMILY_KEYWORD_RULES:
        if any(keyword in normalized for keyword in keywords):
            return family
    return None


_SYSTEM_PROMPT = (
    "You classify IT/technical staffing job titles into a job family for "
    "a recruiting taxonomy. Given a job title and a list of already-used "
    "family names, pick the SINGLE best-fitting family from that list. "
    "Only if truly none of them fit, invent a new family name of 1-3 "
    "words (e.g. 'Cybersecurity'). Return only the family name, nothing "
    "else -- no punctuation, no explanation, no quotation marks."
)


def classify_job_title_family(title: str, known_families: list[str]) -> tuple[str, str]:
    """Returns (family, method) -- method is 'deterministic', 'llm', or
    'none', so a caller can tell which titles still genuinely need a
    human's eye (method='none' means neither path could place it).
    Deterministic first, always; LLM only runs when no keyword rule
    matched, and only if LiteLLM is actually configured -- a missing key
    never blocks a bulk classification pass, those titles just stay
    unclassified for a human, same as before this existed.
    """
    deterministic = classify_family_deterministically(title)
    if deterministic:
        return deterministic, "deterministic"

    if not litellm_configured():
        return "Unclassified", "none"

    user_prompt = f"Job title: {title}\nExisting families: {', '.join(sorted(known_families))}"
    messages = [
        PromptRenderedMessage(role="system", content=_SYSTEM_PROMPT),
        PromptRenderedMessage(role="user", content=user_prompt),
    ]

    try:
        output, _usage = _call_litellm_with_model(
            messages, model=os.getenv("HERMES_PROMPT_DEFAULT_MODEL", "anthropic/claude-haiku-4-5")
        )
    except Exception:  # noqa: BLE001
        return "Unclassified", "none"

    family = (output or "").strip().strip('"').strip(".")
    return (family, "llm") if family else ("Unclassified", "none")


# Words that describe seniority/level rather than the role itself --
# stripped before comparing titles so "Senior Java Developer" and "Java
# Developer" are recognized as the same underlying role at different
# levels, not two titles that happen to share three words.
_SENIORITY_WORDS = {
    "sr", "jr", "senior", "junior", "mid", "entry", "level", "staff",
    "lead", "principal", "director", "associate", "i", "ii", "iii", "iv",
}
# Generic role suffixes so common ("Developer", "Engineer") that sharing
# only one of these tells you almost nothing -- "Java Developer" and
# "Python Developer" both being "Developer" doesn't make them related.
# A match on these alone only counts when the two titles are ALSO in the
# same family (see compute_related_job_titles); a shared word outside
# this set (a real technology/domain term) counts on its own.
_GENERIC_ROLE_WORDS = {
    "developer", "engineer", "consultant", "analyst", "manager",
    "architect", "specialist", "administrator", "coordinator", "officer",
}
_STOP_WORDS = {"and", "or", "of", "the", "a", "an", "for", "with", "&"}
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _title_tokens(title: str) -> set[str]:
    words = _TITLE_TOKEN_RE.findall(title.lower())
    return {w for w in words if w not in _SENIORITY_WORDS and w not in _STOP_WORDS}


def compute_related_job_titles(
    title: str,
    family: str | None,
    other_entries: list[dict],
    max_related: int = 8,
) -> list[str]:
    """Deterministic "titles that mean roughly the same role" finder --
    no LLM, just token overlap, so it's free to run on every add/update
    and on a full-taxonomy backfill without worrying about rate limits
    or cost. Two titles are related when they share at least one "core"
    word -- a real technology/domain term, never a bare seniority or
    generic role word -- e.g. "Java Developer" <-> "Senior Java Engineer"
    via "java". Deliberately requires a core-word match and nothing
    looser: an earlier version also related same-family titles that only
    shared a generic role word ("Java Developer" <-> "Python Developer",
    both Software Engineering, sharing only "developer") -- too broad to
    be useful, since most titles in the same family share SOME generic
    role word by construction. family is accepted for a future finer-
    grained tiebreak but currently only used to prefer a same-family
    match when scores are otherwise tied (see the sort key below).

    Scored, not just filtered, so the ordering favors the closest
    matches first when there are more candidates than max_related --
    more shared core words ranks above one.
    """
    tokens = _title_tokens(title)
    core_tokens = tokens - _GENERIC_ROLE_WORDS
    if not core_tokens:
        return []

    scored: list[tuple[int, str]] = []
    for other in other_entries:
        other_title = other.get("title")
        if not other_title or other_title.strip().lower() == title.strip().lower():
            continue

        other_tokens = _title_tokens(other_title)
        other_core = other_tokens - _GENERIC_ROLE_WORDS
        shared_core = core_tokens & other_core

        if not shared_core:
            continue

        score = len(shared_core) * 10 + len(tokens & other_tokens)
        if family and family != "Unclassified" and other.get("family") == family:
            score += 1

        scored.append((score, other_title))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [t for _score, t in scored[:max_related]]
