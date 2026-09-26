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
        ["ai engineer", "ai scientist", "ai consultant", "ai lead", "ai platform", "ai solution",
         "ai governance", "ai enablement", "ai evaluation", "ai fabric", "ai technical", "ai ml", "ai sdlc",
         "machine learning", "ml engineer", "ml ops", "mlops", "genai", "gen ai", "generative ai",
         "agentic ai", "llm engineer", "nlp engineer", "agentops", "conversational ai"],
    ),
    (
        "Data",
        ["data engineer", "data analyst", "data scientist", "data model", "data governance", "data management",
         "data quality", "data conversion", "data migration", "data integration", "data analytics", "data curation",
         "data transformation", "data consultant", "data risk", "information governance", "reporting analyst", "reporting specialist",
         "database", " dba ", "sql admin", "sql lead", "snowflake", "databricks", "informatica", "talend",
         "alteryx", "microstrategy", "power bi", "tableau", "cognos", "collibra", "neo4j", "bigdata",
         "big data", " etl ", "data warehouse", "business intelligence", " bi ", "bi developer", "bi analyst",
         "bi tech", "analytics engineer", "data architect", "fabric support", "microsoft fabric", "otbi", "obiee",
         "infosphere mdm", "ibm cmod", "edi analyst", "azure adf", "azure data factory"],
    ),
    (
        "Cybersecurity",
        ["cybersecurity", "cyber security", "information security", "application security", "cloud security",
         "data security", "network security", "security analyst", "security consultant", "security technical",
         "security operations", "security compliance", "security vulnerability", "security control", "security officer",
         " soc ", " siem ", " soar ", " grc ", "tprm", "iam ", " iam", "identity access", "identity and access",
         "sailpoint", "saviynt", "cyberark", "penetration tester", "threat analyst", "threat response",
         "cyber detection", "firewall", "palo alto", "itgc", "risk compliance", "risk and compliance"],
    ),
    (
        "Quality Engineering",
        [" qa ", "quality engineer", "quality analyst", "quality assurance", "quality manager", "quality specialist",
         "quality systems", "quality control", "test engineer", "tester", "testing", "test lead", "sdet",
         "automation tester", "qa lead", "uat ", " uat", "validation analyst", "validation support",
         "regulatory compliance", "regulatory research", "qms ", "accessibility sme", "loadrunner", "functional safety",
         "site qualification", "quality regulatory"],
    ),
    ("HCM", [" hcm ", "human capital", " hris ", "workday", "ukg", "kronos", "payroll", "successfactors"]),
    ("Healthcare Management", ["epic ", " epic", "cerner", "ehr ", " ehr", "fhir", "hl7", "medical coder", "healthcare systems"]),
    ("Robotic Process Automation", ["robotic process", " rpa ", "power automate", "automation specialist"]),
    ("ERP", [" sap ", "sap ", " s4 ", "s4hana", " erp ", "oracle ", "oracle fusion", "oracle cloud", "oracle apps",
             "oracle scm", "oracle financial", "oracle otm", "oracle wms", "oracle epm", "oracle adf", "oracle oic",
             "oracle fdi", "oracle fah", "oracle dba", " jd edwards", " jde ", "peoplesoft", "netsuite", "d365",
             "dynamics 365", "dynamics crm", "salesforce", "sfdc", "servicenow", "manhattan active", "mawm", "wmos",
             "kinaxis", "onestream", "anaplan", "blue yonder", "guidewire", "sterling oms", "ibm sterling", "maximo",
             "teamcenter", "windchill", "enovia", "plm ", " plm", "veeva", "appian", "pega ", " pega", "fico ",
             "model n", "facets", "camstar", "opcenter", "epicor", "crunchtime", "one shield", "oneshield",
             "abap", "hana consultant", " wms ", "wms ", "global order promising", "supply chain consultant",
             "materials management", "source to pay", "procurement", "inventory workforce", " pp qm", "package implementation"]),
    (
        "Infrastructure",
        ["network engineer", "network analyst", "network technician", "network admin", "network lead", "network consultant",
         "networking technician", "systems administrator", "system administrator", "system admin", "systems admin",
         "sysadmin", "cloud engineer", "cloud platform", "cloud native", "devops",
         "site reliability", " sre ", "infrastructure", "platform engineer", "platform admin", "cloud architect",
         "technical support", "technology support", "desktop support", "desktop administrator", "helpdesk", "help desk",
         "application support", "production support", "operations support", "field support", "site support",
         "it support", "support analyst", "support specialist", "support consultant", "support technician",
         "field service technician", "av technician", "network operations", "web server administrator", "azure administrator",
         "ci cd administrator", "mq ace administrator", "mq ace", "dynatrace", "grafana", "device management",
         "linux", "windows vmware", "citrix", "openshift", "kubernetes", "datacenter", "data center", "lan ",
         "noc ", "service desk", "exchange online", "microsoft 365", "office 365", "atlassian", "jira admin",
         "kafka admin", "kong admin", "aem administrator", "polarion administrator", "workfront system"],
    ),
    ("Architecture", ["architect"]),
    ("Recruiting", ["recruiter", "talent acquisition", "sourcer", "bench sales", " staffing "]),
    ("Sales", [" sales ", "account executive", "business development", " gtm ", "go to market", "lifecycle marketing",
               "customer account manager", "marketing automation"]),
    ("Business Analysis", ["business analyst", "business solution analyst", "business system analyst", "business process analyst",
                           "systems analyst", "system analyst", "functional analyst", "technical analyst", "configuration analyst",
                           "financial analyst", "operations analyst", "supply chain analyst", "pricing rating analyst", "it bus analyst",
                           "business process consultant", "business consultant", "compliance analyst", "quote project analyst",
                           "service design analyst", "competitive intelligence analyst", "process improvement", " ba "]),
    ("Project Management", ["project manager", "program manager", "program technology manager", "technical pm", "scrum master",
                            "scrum lead", "delivery manager", "delivery lead", "project coordinator", "project controls scheduler",
                            "change management", "change enablement", "organizational change", " ocm ", "agile coach",
                            "program operations manager", "construction manager", "training manager", " pmo "]),
    ("Product", ["product manager", "product owner", "product analyst", "product specialist", "product consultant",
                 "product management", "product technical manager"]),
    ("Design", ["ux designer", "ux researcher", "ui designer", "graphic designer", "product designer", "visual designer",
                "mechanical designer", "structural designer", "pcb designer", "creo designer", "drafter"]),
    ("ITSM", ["service desk", "help desk", " itsm ", "it support", "desktop support"]),
    (
        "Software Engineering",
        ["developer", "development", "engineer", "programmer", "full stack", "backend", "front end", "frontend", "software",
         "technical lead", "technology lead", "tech lead", "integration lead", "integration specialist", "api integration",
         "application development", "solution lead", "technical consultant", "techno functional", "implementation consultant",
         "java", "python", "golang", " go ", "c++", " c ", "dot net", " net ", "react", "angular", "php", "android",
         "ios ", "api ", " api", "mainframe", "cobol", "tibco", "webmethods", "boomi", "mulesoft", "workato",
         "powerbuilder", "embedded", "fpga", "soc verification", "blockchain", "microservices", "reactive programming",
         "power platform consultant", "azure logic apps", "technical team lead", "edi consultant", "business integration manager",
         "business integrations manager", "application designer", "delta v automation", "deltav automation"],
    ),
]

_NON_TITLE_EXACT = {
    "agentic", "available consultant", "aws", "electrical", "hashtag",
    "hello", "m", "power platform", "remote", "remote va",
}
_NON_TITLE_PREFIX_RE = re.compile(r"^(?:flexible\b|hello\b|hi\b|i am\b|i have\b|looking for\b)", re.I)


def _normalize(title: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()} "


def looks_like_non_title(title: str) -> bool:
    compact = _normalize(title).strip()
    return compact in _NON_TITLE_EXACT or bool(_NON_TITLE_PREFIX_RE.match(compact))


def classify_family_deterministically(title: str) -> str | None:
    if looks_like_non_title(title):
        return None
    normalized = _normalize(title)
    for family, keywords in _FAMILY_KEYWORD_RULES:
        if any(keyword in normalized for keyword in keywords):
            return family
    return None


_SYSTEM_PROMPT = (
    "You classify IT/technical staffing job titles into a job family for "
    "a recruiting taxonomy. Given a job title and a list of already-used "
    "family names, pick the SINGLE best-fitting family from that list. "
    "You must use one of the supplied family names. If none fit, return "
    "Unclassified. Return only the family name, nothing "
    "else -- no punctuation, no explanation, no quotation marks."
)


def classify_job_title_family(title: str, known_families: list[str], *, allow_llm: bool = False) -> tuple[str, str]:
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

    if not allow_llm or not litellm_configured():
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
    known_by_key = {item.casefold(): item for item in known_families}
    resolved = known_by_key.get(family.casefold())
    return (resolved, "llm") if resolved else ("Unclassified", "none")


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
