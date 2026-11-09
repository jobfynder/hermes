"""Second-tier deterministic rules for the taxonomy review queues.

The first tier (candidates._is_noise_skill_term, skill_quality.skill_noise_reason,
the boilerplate safe-pattern list) only decides when it is certain. Everything
else used to be "left for review", so the same few hundred skills and
thousands of boilerplate lines sat in the human queue forever.

What the production queue actually contained (2026-11-09):
  * skills: soft/process phrases ("high-quality delivery", "issue fixing"),
    section headings ("Key Must-Have Skills"), bullet-marker artefacts
    ("o Claims"), job titles -- none of them tools or technologies -- mixed
    with a few real product names (RevPro, AirWatch, DataWeave 2.x).
  * boilerplate lines: ~6,000 real job-description requirement lines that
    repeat across 20-35 senders because vendors repost the same job. That is
    duplicated job content, not a footer, and must never be stripped.

Every function returns (decision, reason) where decision is one of
'approve' | 'reject' | 'review' and reason is a short plain-English
explanation shown to the human in the dashboard. Rules are asymmetric on
purpose: rejecting a candidate is conservative (nothing is ever stripped or
added), approving changes matching and stripping, so approvals need a strong
positive signal and everything ambiguous stays 'review' with a suggestion.
Pure functions, no I/O.
"""

from __future__ import annotations

import re

APPROVE, REJECT, REVIEW = "approve", "reject", "review"

_FUNCTION_WORDS = {
    "and", "or", "of", "to", "in", "for", "with", "across", "on", "by", "the",
    "a", "an", "at", "from", "into", "as", "is", "are", "be", "that", "which",
}
_PHRASE_NOUNS = {
    "delivery", "governance", "readiness", "management", "processes", "process",
    "activities", "outputs", "requirements", "expectations", "responsibilities",
    "duties", "profile", "candidates", "candidate", "experience", "exp", "skills",
    "skill", "environment", "environments", "strategies", "strategy", "practices",
    "methodology", "methodologies", "operations", "deliverables", "traceability",
    "fixing", "debugging", "translation", "direction", "understanding", "knowledge",
    "standards", "approach", "support", "reporting", "planning", "resources",
}
_GENERIC_TAIL = {
    "platforms", "platform", "design", "application", "applications", "logs", "txt", "files",
    "tools", "systems", "services", "solutions", "technologies", "environment", "workflows",
}
_HEADING_RE = re.compile(
    r"(?i)\b(?:must[- ]have|nice[- ]to[- ]have|primary|secondary|additional|desired|key|"
    r"required|preferred|good[- ]to[- ]have)\b.*\b(?:skills?|duties|profile|requirements?|"
    r"activities|responsibilit(?:y|ies)|qualifications?)\b"
    r"|\b(?:candidates? only|visa candidates?|desired candidate|job description)\b"
)
_ROLE_WORD_RE = re.compile(
    r"(?i)\b(?:engineer|developer|architect|analyst|administrator|manager|consultant|"
    r"lead|specialist|tester|trainer|coordinator|director|programmer|technician|"
    r"scientist|designer|officer|sme)\b$"
)
_BULLET_PREFIX_RE = re.compile(r"^(?:[o•●▪\-–*]|\d+[.)])\s+\S")
_CAMEL_RE = re.compile(r"[a-z][A-Z]")          # RevPro, AirWatch, DataWeave, GiST
_TECH_MARK_RE = re.compile(r"[0-9]|_|\.[a-z0-9]|::|\+\+|#")   # Auth0, pg_restore, 2.x, C#
_PRODUCT_SUFFIX_RE = re.compile(r"(?i)\b(?:ide|sdk|api|cli|plugin|framework|platform|studio|suite|"
                                r"server|db|sql|ui|ux)\b$")
_WORD_RE = re.compile(r"[A-Za-z0-9+#._\-]+")


def _clean(term: str) -> str:
    return re.sub(r"\s+", " ", term or "").strip()


def skill_decision(term: str, *, catalogued: bool = False) -> tuple[str, str]:
    """Second-tier verdict for a skill candidate that the first tier left."""
    value = _clean(term)
    words = _WORD_RE.findall(value)
    lower = [w.lower() for w in words]

    if _BULLET_PREFIX_RE.match(value):
        return REJECT, "Starts with a list-bullet marker: a parsing artefact, not a skill name."
    if _HEADING_RE.search(value):
        return REJECT, "A section heading copied from the email, not a skill."
    if _ROLE_WORD_RE.search(value) and not catalogued:
        return REJECT, "A job title or role, not a skill (job titles are tracked separately)."
    if len(words) >= 3 and any(w in _FUNCTION_WORDS for w in lower[1:-1]) and not catalogued:
        return REJECT, "A descriptive phrase, not a tool or technology name."
    if len(words) >= 2 and value == value.lower() and not catalogued:
        return REJECT, "An all-lowercase phrase: a description, not a product name."
    if len(words) == 1 and value == value.lower() and not catalogued and not _TECH_MARK_RE.search(value):
        return REJECT, "A common lowercase word, not a product name."
    if len(words) >= 2 and lower[-1] in _PHRASE_NOUNS and not catalogued:
        return REJECT, "Ends in a process/practice word (e.g. 'delivery', 'governance'): a way of working, not a tool."

    if re.search(r"(?i)\.(?:txt|csv|pdf|docx?|xlsx?|json|xml|log|md|zip)$", value) and not catalogued:
        return REJECT, "A file name, not a skill."
    if re.search(r"[:&]", value) and not catalogued:
        return REJECT, "A composite label (contains ':' or '&'), not a single tool name."
    if re.match(r"(?i)^(?:tier|level|l|t)\s*-?\s*\d+\b", value) and not catalogued:
        return REJECT, "A support/seniority tier label, not a skill."
    if len(words) == 1 and re.fullmatch(r"[a-z]+\d{4,}", value) and not catalogued:
        return REJECT, "Looks like a username or ID, not a skill."

    strong = bool(_CAMEL_RE.search(value) or _TECH_MARK_RE.search(value) or _PRODUCT_SUFFIX_RE.search(value))
    generic_tail = lower[-1] in _GENERIC_TAIL if len(words) > 1 else False
    if catalogued or (strong and len(words) <= 2 and not generic_tail
                      and not any(w in _FUNCTION_WORDS for w in lower)):
        return APPROVE, "Looks like a product or technology name (distinctive spelling) seen across several senders."
    if len(words) <= 2 and all(w[:1].isupper() for w in words):
        return REVIEW, "A capitalised name. Could be a product, a place or a person. Needs a human decision."
    return REVIEW, "Not clearly a tool or a phrase. Needs a human decision."


# ---- boilerplate ---------------------------------------------------------

_JOB_CONTENT_START_RE = re.compile(
    r"(?i)^(?:collaborat\w*|ensur\w*|drive|driving|participat\w*|represent\w*|mentor\w*|validat\w*|"
    r"review\w*|perform\w*|monitor\w*|maintain\w*|install\w*|optimi[sz]\w*|troubleshoot\w*|stay|"
    r"support\w*|develop\w*|design\w*|implement\w*|manage\w*|lead\w*|build\w*|create\w*|configur\w*|"
    r"deploy\w*|test\w*|analy[sz]\w*|document\w*|coordinat\w*|provid\w*|deliver\w*|own\w*|work\w*|"
    r"assist\w*|execut\w*|plan\w*|prepar\w*|conduct\w*|identif\w*|resolv\w*|communicat\w*|"
    r"strong|solid|deep|excellent|good|proven|hands[- ]on|familiarity|understanding|knowledge|"
    r"experience|ability|proficien\w*|expertise|exposure|working|demonstrat\w*|required|minimum|"
    r"preferred|must|should|ideal|background|certif\w*|bachelor|master|degree|"
    r"database|query|data|cloud|security|network|service|application|system|infrastructure|"
    r"incident|release|change|release|sap|oracle|aws|azure|java|python|sql)\b"
)
_TECH_WORD_RE = re.compile(
    r"(?i)\b(?:databricks|aws|azure|gcp|sql|python|java|javascript|kafka|spark|etl|elt|api|"
    r"db2|oracle|sap|salesforce|servicenow|itil|agile|scrum|devops|docker|kubernetes|linux|"
    r"selenium|automation|database|lakehouse|lake house|delta lake|framework|architecture)\b"
)
_JOB_NOUN_RE = re.compile(
    r"(?i)\b(?:experience|skills?|requirements?|responsibilit\w+|ability|knowledge|stakeholders?|"
    r"architect\w*|implement\w*|development|developer|integration|testing|enterprise|systems?|"
    r"applications?|projects?|teams?|candidates?|data|platforms?|workflows?|framework\w*|reporting|"
    r"governance|compliance|procedures?|standards?|analysis|planning|operations?|migration|"
    r"performance|quality|service levels?|qualifications?|certifications?|years?|degree|"
    r"engineering|infrastructure|deployment|monitoring|documentation|production|technical|"
    r"interview\w*|shift|onsite|on-site|remote|hybrid|contract\w*|duration|rate|visa|position|"
    r"rotation|work arrangement|self-starter|flexib\w+|adaptab\w+|initiative|ownership|"
    r"accountab\w+|proactive|critical|issues?|servers?|support|manag\w+|configur\w+|"
    r"administ\w+|tagging|command|principles?|inventory|co-?ordinat\w+|security|privacy|"
    r"timely|completion|meeting\w*|status|reports?|budget|forecast\w*|process\w*|practices?)\b"
)
_REAL_FOOTER_RE = re.compile(
    r"(?i)(?:unsubscribe|opt[- ]?out|privacy|confidential|disclaimer|intended recipient|"
    r"all rights reserved|©|copyright|reply to|e-?mail us|call us|visit us|follow us|"
    r"to apply|send (?:your )?(?:resume|cv)|regards|sincerely|thanks[,!]? ?$|"
    r"this (?:e-?mail|message)|you are receiving|view in browser|equal opportunity)"
)


def boilerplate_decision(term: str, *, senders: int = 0, occurrences: int = 0) -> tuple[str, str]:
    """Second-tier verdict for a boilerplate-line candidate.

    A line seen from many senders is only boilerplate if it is footer-shaped.
    A requirement or duty line repeated by many vendors is the same *job*
    being reposted, so it is rejected ("not boilerplate: keep in the job
    description"). Rejecting never strips anything from any email.
    """
    value = _clean(term)
    if _REAL_FOOTER_RE.search(value):
        return REVIEW, "Looks like a footer or legal line. Approve to strip it from every future job description."
    words = value.split()
    # Bullet/list artefacts are always job-description layout, never a footer.
    bare = re.sub(r"^(?:[*·•●▪o\-–.]+\s+)+", "", value)
    if (_JOB_CONTENT_START_RE.match(bare) or _TECH_WORD_RE.search(bare) or _JOB_NOUN_RE.search(bare)
            or bare != value or value.endswith((":", ";", ",")) or len(words) >= 14
            or value.startswith(('"', "'")) or bare.count(",") >= 2):
        return REJECT, ("Real job-description content that many vendors repost. It is not a footer, "
                        "so it stays in the job description.")
    if len(words) <= 3:
        return REJECT, "Too short and generic to be a reliable boilerplate line."
    return REVIEW, "Not clearly job content or a footer. Needs a human decision."
