"""Deterministic job-title recovery from a recruiter email's subject line.

Why this exists: in production the single largest remaining review reason
after company_missing was job_title_missing (~3,400 drafts in needs_review).
Nearly every one of them (3,458 of 3,459 sampled) had a subject line with
the title in it, wrapped in recruiter noise the original extractor
(app/understanding/parsers/basic.py: extract_probable_title) cannot see
through: "Urgent Requirement :: Data Scientist (...) :: Franklin",
"Contract || Data Ingestion Developer || Liberty, NC 27298 (Remote)",
"Full Stack Python Developer Location: San Francisco Bay Area, CA",
"Group - Vendors & Clients Hub **HIRING: Oracle Fusion Consultant**",
"Now Hiring: Scrum Master-Charlotte, NC".

Deliberately a SEPARATE fallback, used only when extract_probable_title
found nothing (see parse_requirement_email): every draft that already has
a title keeps exactly the title it has today, so this can only fill gaps,
never change an existing answer. Fully deterministic -- no LLM, no I/O.

Precision control is the title-keyword gate: a candidate segment must
contain a recognisable role word, so segments that are only noise
("Contract", "Immediate Interview", "Onsite - CA") are never returned,
and bench/hotlist-style subjects ("60+ Pre-Screened Consultants") are
rejected outright.
"""

from __future__ import annotations

import re
from html import unescape

# Role words, case-insensitive, whole-word.
_TITLE_WORD = re.compile(
    r"\b(?:developer|engineer|architect|analyst|administrator|admin|manager|"
    r"consultant|recruiter|lead|designer|researcher|technician|scientist|"
    r"specialist|tester|programmer|coordinator|director|executive|officer|"
    r"owner|writer|dba|sme|sdet|master|expert|advisor|representative|"
    r"supervisor|strategist|support|devops|sre|developers|engineers|"
    r"analysts|architects|consultants|administrators|eng|dev|auditor|"
    r"accountant)\b",
    re.IGNORECASE,
)
# Short role acronyms that are only reliable when written in capitals
# ("SALESFORCE BA", "TPM") -- case-sensitive on purpose.
_TITLE_ACRONYM = re.compile(r"\b(?:BA|BSA|TPM|SDET|QA|SDE)\b")

# Leading recruiter phrases that are never part of the title. Applied
# repeatedly ("Urgent Requirement : Hiring - X").
_LEADING_NOISE = re.compile(
    r"^(?:"
    r"(?:re|fw|fwd)\s*:|"
    r"action\s+required\s*:?|submit\s+profiles?\s+for\b|"
    r"(?:the|an?)\s+(?=\S)|"
    r"\d{1,2}[.)]\s+|\d{1,2}\+\s+|"
    r"(?:urgent(?:ly)?|immediate(?:ly)?|hot|new|now|fresh|priority|asap|alert|"
    r"multiple|strong\s+fit\s+for\s+your|better\s+opportunit(?:y|ies))\b|"
    r"(?:hiring|requirements?|req|open(?:ing)?s?|openn?ings?|vacanc(?:y|ies)|"
    r"need(?:ed)?|looking(?:\s+for)?|seeking|available|opportunit(?:y|ies)|"
    r"interviews?|contract|c2c|w2|full[\s-]?time|part[\s-]?time|"
    r"remote\s+job|remote|onsite|hybrid|f2f|job|job\s+description)\b"
    r"(?:\s*(?:for|of|:|-|!+|\.)\s*|\s+)|"
    r"for\s+(?:the\s+)?(?:job\s+)?(?:role\s+|position\s+)?|"
    r"(?:job\s+)?(?:role|position)\s*(?::|-|for\b)\s*|"
    r"[-:!#*~\u2022|_\s]+"
    r")",
    re.IGNORECASE,
)

# Segment delimiters used by recruiters between title / location / terms.
_SEGMENT_SPLIT = re.compile(
    r"\s*(?:\|\||\||:+-?|;|--+|\s//\s|\s[-–—]\s|\s@\s|~|•|\s/\s|"
    r"\s_\s|_\s+)\s*"
)

# Emoji / pictographs recruiters paste into subjects ("🚨 HIRING ...").
_PICTOGRAPHS = re.compile("[\U0001F000-\U0001FFFF☀-➿️​]")

# "Title Location: Houston" / "Title Duration: 6 months": everything from
# the first field label onward is not the title.
_FIELD_LABEL_CUT = re.compile(
    r"\s+(?:work\s+)?(?:locations?|loc|duration|rate|visa|client|end\s*client|"
    r"position\s*type|experience|exp)\s*:+.*$",
    re.IGNORECASE,
)

_REQ_ID = re.compile(r"\b(?:[A-Z]{2,6}[-_ ]?\d{3,}(?:[-_]\d+)?|\d{4,}(?:-\d+)?)\b")

# Trailing clauses that are conditions, not title.
_TRAILING_CLAUSE = re.compile(
    r"\s+(?:with|having|who|must|only|needs?|ready|locals?|local\s+only|"
    r"for|based|onsite|hybrid|remote|contract|c2c|w2|opt|usc|gc|h1b|h4)\b.*$",
    re.IGNORECASE,
)

_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|"
    "MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|"
    "WV|WI|WY"
)
# "... at Concord, CA", "... in Phoenix, AZ" -- location-shaped suffix only
# (requires a real state code), so "Software Development Engineer in Test"
# survives.
_LOCATION_SUFFIX = re.compile(
    r"\s+(?:in|at)\s+[A-Z][A-Za-z./]+(?:\s+[A-Z][A-Za-z./]+){0,2}\s*,?\s*(?:"
    + _STATES
    + r")\b.*$"
)
# "Lead Frontend Engineer, San Francisco, CA" (comma-led: city may be up to
# three words) / "Engineer II Arlington, VA" (no comma: a single city word
# only, so "Program Manager Alameda, CA" does not eat "Program Manager").
_CITY_STATE_COMMA_SUFFIX = re.compile(
    r",\s+(?:[A-Z][A-Za-z.]+\s+){0,2}[A-Z][A-Za-z.]+\s*,\s*(?:" + _STATES + r")\b.*$"
)
_CITY_STATE_SUFFIX = re.compile(
    r"\s+[A-Z][A-Za-z.]+\s*,\s*(?:" + _STATES + r")\b.*$"
)
# "Scrum Master-Charlotte, NC" -- hyphen glued to a city/state.
_GLUED_LOCATION = re.compile(r"-\s*[A-Z][A-Za-z .]+,\s*(?:" + _STATES + r")\b.*$")

# Parenthetical that is only terms/visa/location noise, or only punctuation
# left behind by an upstream strip -- not "(.NET)", "(SDET)", "(LBA)".
_NOISE_PAREN = re.compile(
    r"\s*\((?:[^()]*\b(?:remote|onsite|on-site|hybrid|local|locals|usc|gc|"
    r"h1b|h4|opt|w2|c2c|contract|interview|visa|exp|experience|required|years?|yrs?)\b[^()]*|"
    r"[\s&,/+\-]*(?:(?:and|or)[\s&,/+\-]*)*|[^()]*%[^()]*)\)",
    re.IGNORECASE,
)

_GROUP_PREFIX = re.compile(
    r"^(?:group\s*-\s*vendors\s*&\s*clients\s*hub|\[[^\]]{2,40}\])\s*",
    re.IGNORECASE,
)

# Trailing filler words left dangling after a cut ("SAP PP Architect in",
# "Qlik Talend Cloud Architect Opportunity").
_DANGLING_TAIL = re.compile(
    r"\s+(?:in|at|for|of|and|or|to|with|opportunit(?:y|ies)|positions?|roles?|"
    r"openings?|requirements?|needed|required|urgent(?:ly)?|hiring|rtr)$",
    re.IGNORECASE,
)

# Leading edge keeps a '.' so ".Net Lead" / ".NET Developer" survive;
# trailing edge strips it.
_LEAD_JUNK = " \t,-:;|~*#\u2022_\"'!/"
_TAIL_JUNK = " \t,-:;.|~*#\u2022_\"'!/"


def _clean_segment(segment: str) -> str:
    text = segment.strip(_LEAD_JUNK).rstrip(_TAIL_JUNK)
    for _ in range(8):
        stripped = _LEADING_NOISE.sub("", text, count=1).strip(_LEAD_JUNK).rstrip(_TAIL_JUNK)
        if stripped == text:
            break
        text = stripped
    # "Maximo Developer **Onsite Dallas**": emphasis markers mid-segment open
    # a location/terms aside, never more title.
    text = re.sub(r"\s+\*\*.*$", "", text)
    text = _REQ_ID.sub(" ", text)
    text = _NOISE_PAREN.sub("", text)
    text = _GLUED_LOCATION.sub("", text)
    text = _LOCATION_SUFFIX.sub("", text)
    text = _CITY_STATE_COMMA_SUFFIX.sub("", text)
    text = _CITY_STATE_SUFFIX.sub("", text)
    text = _TRAILING_CLAUSE.sub("", text)
    text = re.sub(r"\s*@.*$", "", text)
    text = re.sub(r"\brtr\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(_LEAD_JUNK).rstrip(_TAIL_JUNK)
    # An unbalanced trailing "(" left by a cut-off subject.
    text = re.sub(r"\s*\([^)]*$", "", text).strip(_LEAD_JUNK).rstrip(_TAIL_JUNK)
    for _ in range(3):
        trimmed = _DANGLING_TAIL.sub("", text).rstrip(_TAIL_JUNK)
        if trimmed == text:
            break
        text = trimmed
    return text


# Bench / hotlist / marketing subjects that contain role words but are not
# a job title ("60+ Pre-Screened Consultants", "Available Consultants").
_NOT_A_JOB = re.compile(
    r"\b(?:pre[-\s]?screened|bench|hot\s*list|hotlist|available\s+consultants?|"
    r"resumes?|profiles?\s+available|mail\s+delivery|newsletter|linkedin|"
    r"unsubscribe|invitation)\b",
    re.IGNORECASE,
)


def _plausible(candidate: str) -> bool:
    if not (3 <= len(candidate) <= 80):
        return False
    if candidate[0].isdigit() or _NOT_A_JOB.search(candidate):
        return False
    words = candidate.split()
    if not (1 <= len(words) <= 9):
        return False
    if not (_TITLE_WORD.search(candidate) or _TITLE_ACRONYM.search(candidate)):
        return False
    letters = sum(ch.isalpha() for ch in candidate)
    return letters >= 3 and letters / max(len(candidate), 1) > 0.6


def extract_subject_title(subject: str | None) -> str | None:
    """Best title found in a subject line, or None.

    Segments are tried left to right and the first plausible one wins, so
    "Urgent Requirement :: Data Scientist :: Franklin" yields "Data
    Scientist" and "Contract || QA Lead || NJ" yields "QA Lead".
    """
    if not subject:
        return None

    # Unescaped twice: subjects arrive double-encoded ("&amp;#128640;").
    text = unescape(unescape(subject))
    text = re.sub(r"\s+", " ", _PICTOGRAPHS.sub(" ", text)).strip()
    text = _GROUP_PREFIX.sub("", text).strip(_LEAD_JUNK)
    text = _FIELD_LABEL_CUT.sub("", text)
    if not text:
        return None

    for segment in _SEGMENT_SPLIT.split(text):
        candidate = _clean_segment(segment)
        if _plausible(candidate):
            return candidate

    return None
