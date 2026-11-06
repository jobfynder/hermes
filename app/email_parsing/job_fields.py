"""Deterministic extraction of the job-board fields Jobfynder Core needs that
the base requirement parser leaves empty.

Measured on 6,000 random production job requirements: employment type was
empty on 59%, rate on ~92%, and nothing captured work mode, duration, start
date or a requisition id at all. Every function here is a pure, zero-LLM gap
filler used only when the existing extractor found nothing, so a value that
exists today never changes (same contract as subject_title.py). Anything
inferred rather than stated is flagged by the caller so reviewers and Core
can tell.
"""

from __future__ import annotations

import re
from typing import Any

_FLAGS = re.IGNORECASE

# ---------------------------------------------------------------- employment
_EMP_LABEL = re.compile(
    r"\b(?:employment|job|position|hire|engagement)\s*type\s*[:\-]\s*([^\n]{1,60})", _FLAGS
)
_EMP_SYNONYMS: list[tuple[str, re.Pattern[str]]] = [
    ("Contract to Hire", re.compile(r"\b(?:contract[\s-]*to[\s-]*hire|c2h|cth)\b", _FLAGS)),
    ("Full-time", re.compile(r"\b(?:full[\s-]?time|fulltime|permanent|perm|direct[\s-]?hire|fte)\b", _FLAGS)),
    ("Part-time", re.compile(r"\bpart[\s-]?time\b", _FLAGS)),
    ("Contract", re.compile(r"\b(?:contract(?:or)?|consultant|sub[\s-]?con\w*|c2c|corp[\s-]to[\s-]corp|1099|temp(?:orary)?)\b", _FLAGS)),
    ("W2", re.compile(r"\bw[\s-]?2\b", _FLAGS)),
]
_DURATION_LABEL = re.compile(
    r"\b(?:duration|contract\s*(?:length|term|duration))\s*[:\-]\s*([^\n]{1,50})", _FLAGS
)
_DURATION_VALUE = re.compile(
    r"(\d{1,2})\s*(\+|plus)?\s*(?:[-–]\s*\d{1,2}\s*)?(months?|mos?|years?|yrs?|weeks?)\b", _FLAGS
)
_LONG_TERM = re.compile(r"\blong[\s-]?term\b", _FLAGS)
_EXPERIENCE_AFTER = re.compile(r"\s*(?:of\s+)?(?:relevant\s+|hands[\s-]on\s+|work\s+|professional\s+)?exp", _FLAGS)


def employment_type_from_label(text: str) -> str | None:
    """A stated 'Job Type / Employment Type: ...' value, mapped to Core's
    vocabulary. Stated, not inferred."""
    match = _EMP_LABEL.search(text or "")
    if not match:
        return None
    value = match.group(1)
    for label, pattern in _EMP_SYNONYMS:
        if pattern.search(value):
            return label
    return None


def parse_duration(text: str) -> dict[str, Any]:
    """{'duration': '12 months', 'duration_months': 12} from an explicit
    'Duration:' label, else from an 'N+ months' phrase; 'Long term' is
    kept as text only (no number to invent)."""
    text = text or ""
    label = _DURATION_LABEL.search(text)
    source = label.group(1) if label else None
    if source is None:
        # Body fallback: only an "N months" phrase that is not an experience
        # requirement ("8+ years of experience", "6 months experience").
        match = next(
            (m for m in _DURATION_VALUE.finditer(text)
             if m.group(3).lower().startswith("m") and not _EXPERIENCE_AFTER.match(text, m.end())),
            None,
        )
    else:
        match = _DURATION_VALUE.search(source)
    if match:
        number = int(match.group(1))
        unit = match.group(3).lower()
        months = number * 12 if unit.startswith(("y",)) else number if unit.startswith("m") else max(1, round(number / 4))
        plus = "+" if match.group(2) else ""
        word = "year" if unit.startswith("y") else "week" if unit.startswith("w") else "month"
        return {
            "duration": f"{number}{plus} {word}{'' if number == 1 else 's'}",
            "duration_months": months,
        }
    if source and _LONG_TERM.search(source):
        return {"duration": "Long term"}
    if _LONG_TERM.search(text):
        return {"duration": "Long term"}
    return {}


def infer_employment_type(text: str, duration: dict[str, Any]) -> tuple[str | None, str | None]:
    """(value, basis). A stated label wins ('label'); otherwise a stated
    engagement length is evidence of a contract ('duration'): a permanent
    role has no 'Duration: 12 months'. No evidence -> (None, None); never a
    blind default."""
    stated = employment_type_from_label(text)
    if stated:
        return stated, "label"
    if duration.get("duration_months") or (duration.get("duration") and _DURATION_LABEL.search(text or "")):
        return "Contract", "duration"
    return None, None


# ----------------------------------------------------------------------- rate
_NUM = r"\d{2,3}(?:,\d{3})?(?:\.\d{1,2})?"
_RATE_UNIT = r"(?:/|per\s*|an?\s*|\s)\s*(?P<unit>hr|hour|hourly|day|daily|month|mo|yr|year|annum|annually|k)\b"
_RATE_RANGE = re.compile(
    rf"\$?\s*(?P<lo>{_NUM})\s*(?P<lok>k)?\s*(?:-|–|to)\s*\$?\s*(?P<hi>{_NUM})\s*(?P<hik>k)?\s*{_RATE_UNIT}", _FLAGS
)
_RATE_SINGLE = re.compile(rf"\$\s*(?P<lo>{_NUM})\s*(?P<lok>k)?\s*{_RATE_UNIT}", _FLAGS)
_RATE_LABELLED = re.compile(
    rf"\b(?:pay\s*rate|bill\s*rate|rate|salary|compensation|pay)\s*[:\-@]\s*\$?\s*(?P<lo>{_NUM})(?:\s*(?:-|–|to)\s*\$?\s*(?P<hi>{_NUM}))?\s*(?P<lok>k)?(?:{_RATE_UNIT})?",
    _FLAGS,
)
_RATE_ON = re.compile(rf"\$?\s*(?P<lo>{_NUM})\s*(?:/\s*hr)?\s*(?:on|@)\s*(?P<basis>c2c|w2|1099)\b", _FLAGS)
_DOE = re.compile(r"\b(?:doe|depends\s+on\s+experience|negotiable|market\s+rate|open)\b", _FLAGS)
_UNIT_MAP = {
    "hr": "hour", "hour": "hour", "hourly": "hour", "day": "day", "daily": "day",
    "month": "month", "mo": "month", "yr": "year", "year": "year", "annum": "year", "annually": "year", "k": "year",
}


def _money(raw: str | None, k: bool) -> float | None:
    if not raw:
        return None
    value = float(raw.replace(",", ""))
    return value * 1000 if k else value


def parse_rate(text: str) -> dict[str, Any]:
    """Structured rate or {}. Requires a unit, a rate label or an 'on C2C/W2'
    marker, so '$2 million budget' or a bare '$5' is never mistaken for pay.
    Returns rate_min, rate_max, rate_unit (hour/day/month/year), rate_text
    and, when stated, rate_basis (C2C/W2/1099)."""
    text = text or ""
    candidates = (m for pattern in (_RATE_RANGE, _RATE_SINGLE, _RATE_LABELLED, _RATE_ON) for m in pattern.finditer(text))
    for match in candidates:
        groups = match.groupdict()
        lo_k = bool(groups.get("lok")) or (groups.get("unit") or "").lower() == "k"
        low = _money(groups.get("lo"), lo_k)
        high = _money(groups.get("hi"), bool(groups.get("hik")) or lo_k) if groups.get("hi") else None
        if low is None:
            continue
        unit_raw = (groups.get("unit") or "").lower()
        unit = _UNIT_MAP.get(unit_raw)
        if unit is None:  # infer unit from magnitude only when unambiguous
            unit = "year" if low >= 1000 else "hour" if 15 <= low <= 400 else None
        if unit is None:
            continue
        if unit == "hour" and not (10 <= low <= 500):
            continue
        if unit == "year" and not (20_000 <= low <= 600_000):
            continue
        # "$499/month" recurs verbatim in vendor/job-board footers; a real
        # monthly pay figure is in the thousands, a daily one in the hundreds.
        if unit == "month" and not (1_000 <= low <= 60_000):
            continue
        if unit == "day" and not (80 <= low <= 3_000):
            continue
        result: dict[str, Any] = {"rate_min": low, "rate_unit": unit, "rate_text": match.group(0).strip(" :-@")}
        if high and high >= low:
            result["rate_max"] = high
        basis = re.search(r"\b(c2c|w2|1099)\b", text[match.start(): match.end() + 25], _FLAGS)
        if groups.get("basis"):
            result["rate_basis"] = groups["basis"].upper()
        elif basis:
            result["rate_basis"] = basis.group(1).upper()
        return result
    if re.search(r"\b(?:rate|salary|pay)\b[^\n]{0,15}", text, _FLAGS) and _DOE.search(
        " ".join(m.group(0) for m in re.finditer(r"\b(?:rate|salary|pay)\b[^\n]{0,25}", text, _FLAGS))
    ):
        return {"rate_text": "DOE"}
    return {}


# ------------------------------------------------------------------ work mode
_MODE_LABEL = re.compile(r"\b(?:work\s*(?:mode|model|type|arrangement)|location\s*type)\s*[:\-]\s*([^\n]{1,40})", _FLAGS)
_MODE_WORDS = {
    "hybrid": re.compile(r"\bhybrid\b|\bhybird\b", _FLAGS),
    "remote": re.compile(r"\b(?:fully\s+|100%\s*)?remote\b|\bwork\s+from\s+home\b|\bwfh\b", _FLAGS),
    "onsite": re.compile(r"\bon[\s-]?site\b|\bin[\s-]office\b|\bf2f\b", _FLAGS),
}
_NEGATED = re.compile(r"\b(?:no|not|non|isn['’]?t|without)\s+(?:a\s+)?(?:fully\s+)?(?:remote|hybrid|on[\s-]?site)\b", _FLAGS)


def parse_work_mode(text: str, subject: str | None = None) -> str | None:
    """REMOTE / HYBRID / ONSITE or None. Stated label first, then the subject
    line (where recruiters put it), then the body with negations ('no
    remote', 'not hybrid') removed. Hybrid outranks remote when both appear
    ('Hybrid, remote candidates considered' is hybrid)."""
    label = _MODE_LABEL.search(text or "")
    for source in (label.group(1) if label else None, subject, text):
        if not source:
            continue
        cleaned = _NEGATED.sub(" ", source)
        found = [mode for mode, pattern in _MODE_WORDS.items() if pattern.search(cleaned)]
        if not found:
            continue
        for mode in ("hybrid", "remote", "onsite"):
            if mode in found:
                return mode.upper()
    return None


# ----------------------------------------------------- start date / requisition
_START = re.compile(
    r"\b(?:start\s*date|start|begin(?:ning)?)\s*[:\-]\s*([^\n]{1,30})|\b(asap|immediate(?:ly)?\s+start|immediate\s+joiner)\b", _FLAGS
)
_REQ = re.compile(
    r"\b(?:req(?:uisition)?|job|position|posting)\s*(?:id|#|no\.?|number|code)\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9_\-]{2,24})", _FLAGS
)


def parse_start_date(text: str) -> str | None:
    match = _START.search(text or "")
    if not match:
        return None
    value = (match.group(1) or match.group(2) or "").strip(" .,;:-")
    return value[:30] or None


def parse_requisition_id(text: str) -> str | None:
    match = _REQ.search(text or "")
    if not match:
        return None
    value = match.group(1).strip("-_")
    return value if re.search(r"\d", value) else None


def extract_job_board_fields(text: str, subject: str | None, existing: dict[str, Any]) -> dict[str, Any]:
    """Gap-fill dict to merge into a requirement record. Keys already carrying
    a value in `existing` are never returned (fill, never override).
    employment_type_basis is set only when the value was inferred rather
    than extracted by the base parser."""
    out: dict[str, Any] = {}
    duration = parse_duration(text)
    for key, value in duration.items():
        out[key] = value

    if not existing.get("employment_type"):
        value, basis = infer_employment_type(text, duration)
        if value:
            out["employment_type"] = value
            out["employment_type_basis"] = basis

    rate = parse_rate(text)
    if rate:
        out.update({k: v for k, v in rate.items() if k != "rate_text"})
        if not existing.get("rate_or_salary") and rate.get("rate_text"):
            out["rate_or_salary"] = rate["rate_text"]

    mode = parse_work_mode(text, subject)
    if mode:
        out["work_mode"] = mode
    start = parse_start_date(text)
    if start:
        out["start_date"] = start
    req = parse_requisition_id(text)
    if req:
        out["requisition_id"] = req
    return out
