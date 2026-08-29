"""Deterministic email signature detection and contact extraction.

Pipeline position (see app/channels/service.py::process_channel_intake):
    raw email -> body cleanup -> signature detection -> field extraction
    -> normalization -> confidence scoring -> structured_data["signature"]

No LLM calls anywhere in this module -- PARSER_METADATA["uses_llm"] is
always False, matching the guarantee every other parser in
app/email_parsing/ makes. Name/company extraction has a secondary NER
fallback (spaCy's en_core_web_sm, already an installed dependency --
see _extract_person_org_via_ner below) for the specific case the
regex-only pass structurally can't handle: a bare "Harry / ITECSUS /
harry@itecsus.com"-style block with no title keyword, no recognizable
company suffix (Inc/LLC/Staffing/...), and no multi-word name on one
line to anchor on. This is a small, fully local statistical model, not
an LLM call -- no network request, no API cost, no per-message latency
beyond a few milliseconds once loaded -- so "uses_llm" stays accurate.
It only ever fills a field the regex pass left empty, same
anti-hallucination rule the rest of this codebase's fallbacks follow;
tagged with its own low-confidence method name (ner_person/ner_org) so
a reviewer can see it's a softer signal than a structural match.
"""

import re
from functools import lru_cache
from typing import Any

try:
    import phonenumbers
except ImportError:  # pragma: no cover - exercised only if dependency missing
    phonenumbers = None

try:
    import spacy
except ImportError:  # pragma: no cover - exercised only if dependency missing
    spacy = None

from app.email_parsing.sender_resolver import forwarded_marker_span
from app.understanding.parsers.contact import EMAIL_PATTERN, LINKEDIN_PATTERN, PHONE_PATTERN


PARSER_METADATA = {
    "name": "hermes_email_signature_parser",
    "version": "hermes_email_signature_parser_v1",
    "uses_llm": False,
}

DEFAULT_PHONE_REGION = "US"

REQUIRES_REVIEW_THRESHOLD = 0.70  # matches app/email_parsing/parsers.py convention


# ---------------------------------------------------------------------------
# Boundary detection: separate the current message from quoted/forwarded
# history and trailing legal/marketing noise (Phase 1 exclusions).
# ---------------------------------------------------------------------------

QUOTE_REPLY_HEADER_RE = re.compile(r"(?im)^\s*on\s+.{0,160}\s+wrote:\s*$")

RAW_HEADER_BLOCK_RE = re.compile(
    r"(?im)^\s*from\s*:\s*.+\r?\n\s*(?:sent|date)\s*:\s*.+"
)

QUOTE_PREFIX_LINE_RE = re.compile(r"^\s*>")

SIGNOFF_RE = re.compile(
    r"(?im)^[ \t>]*(?:-{2,}|thanks(?:\s+(?:so much|again))?|thank you|"
    r"regards|best regards|kind regards|warm regards|warmest regards|best|"
    r"sincerely|cheers|respectfully)[ \t]*[,.!]?[ \t]*$"
)

SIGNOFF_INLINE_NAME_RE = re.compile(
    r"(?im)^[ \t>]*(?:thanks|thank you|regards|best regards|kind regards|"
    r"warm regards|warmest regards|best|sincerely|cheers|respectfully)"
    r"[ \t]*,\s*(?P<name>[A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+){0,3})\s*$"
)

SENT_FROM_DEVICE_RE = re.compile(
    r"(?im)^\s*sent from my (?:iphone|ipad|android|samsung(?:\s+device)?|"
    r"mobile device|blackberry)\s*\.?\s*$"
)

DISCLAIMER_START_RE = re.compile(
    r"(?im)^\s*(?:"
    r"this\s+(?:e-?mail|message|transmission|communication)\b.{0,160}"
    r"(?:confidential|privileged|intended (?:solely|only) for)"
    r"|confidentiality notice"
    r"|if you (?:are not|have received this)\b.{0,160}"
    r"(?:intended recipient|in error)"
    r"|to\s+unsubscribe\b"
    r"|click here to unsubscribe"
    r"|manage your (?:email )?preferences"
    r"|update your (?:email )?preferences"
    r"|you are receiving this (?:email|message) because"
    r"|this email was sent to\b"
    r")"
)

SOCIAL_BOILERPLATE_RE = re.compile(
    r"(?i)\b(?:follow us on|find us on|connect with us on|like us on)\b"
)

TRACKING_URL_RE = re.compile(
    r"(?i)https?://(?:[\w-]+\.)*(?:list-manage\.com|mailchi\.mp|"
    r"sendgrid\.net|hubspotlinks\.com|mandrillapp\.com|"
    r"constantcontact\.com|campaign-archive\.com|click\.[\w.-]+)"
)


_FORWARDED_HEADER_LINE_RE = re.compile(
    r"(?im)^\s*(?:from|sent|date|to|subject|cc|bcc)\s*:.*$"
)


def _skip_forwarded_header_block(lines: list[str], start: int) -> int:
    """Given the line index where a forwarded-message header block begins
    (RAW_HEADER_BLOCK_RE only matches its first two lines -- From:/Sent:),
    returns the index just past the full contiguous From:/Sent:/To:/
    Subject:/Cc:/Bcc: run (and any blank lines among them). That's where
    the forwarded sender's own signature-like info actually starts, not
    the header block itself -- scanning from `start` directly picks up
    the header's own "Subject: ..." line as if it were signature content.
    """

    index = start

    while index < len(lines) and (
        not lines[index].strip() or _FORWARDED_HEADER_LINE_RE.match(lines[index])
    ):
        index += 1

    return index


def _strip_quote_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:>\s*)+", "", line)


def _quote_boundary_index(lines: list[str]) -> int | None:
    """First line index where quoted/forwarded history begins, or None if
    the whole body is a single (top) message. Bounds Phase 6 (don't parse
    a signature that only appears inside quoted history) and keeps Phase 1
    from treating a quoted sender's signature as this message's own."""

    text = "\n".join(lines)

    forward_span = forwarded_marker_span(text)
    if forward_span is not None:
        return text.count("\n", 0, forward_span[0])

    header_block_match = RAW_HEADER_BLOCK_RE.search(text)
    if header_block_match is not None:
        return text.count("\n", 0, header_block_match.start())

    for index, line in enumerate(lines):
        if QUOTE_REPLY_HEADER_RE.match(line) or QUOTE_PREFIX_LINE_RE.match(line):
            return index

    return None


def _disclaimer_boundary_index(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if DISCLAIMER_START_RE.match(lines[index]):
            return index
    return None


# ---------------------------------------------------------------------------
# Field-level patterns (Phase 2).
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[\w.-]+\.[a-z]{2,}(?:/[^\s<>\"']*)?")

TITLE_KEYWORDS_RE = re.compile(
    r"(?i)\b(?:senior|sr\.?|junior|jr\.?)?\s*(?:technical )?recruiter\b|"
    r"\btalent (?:acquisition|sourcer)\b|\bsourcer\b|"
    r"\baccount (?:manager|executive)\b|\bhuman resources\b|\bhr\b|"
    r"\bdirector\b|\bmanager\b|\bengineer\b|\bconsultant\b|\bspecialist\b|"
    r"\bcoordinator\b|\banalyst\b|\bexecutive\b|\bofficer\b|\blead\b|"
    r"\bpresident\b|\bceo\b|\bcto\b|\bcfo\b|\bvp\b|\bvice president\b|"
    r"\bstaffing\b|\bdelivery (?:manager|lead)\b|\bbusiness development\b|"
    r"\bbench sales\b"
)

COMPANY_SUFFIX_RE = re.compile(
    r"(?i)\b(?:inc\.?|llc\.?|llp\.?|ltd\.?|corp\.?|corporation|staffing|"
    r"solutions|technologies|technology|systems|group|consulting|services)\b"
)

NAME_LINE_RE = re.compile(
    r"^[A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+){1,3}$"
)

CITY_STATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z. ]{1,30}?),\s*([A-Z]{2})\b(?:\s+(\d{5})(?:-\d{4})?)?"
)

PHONE_LABEL_RE = re.compile(
    r"(?i)\b(mobile|cell)\s*[:\-]|\b(phone|office|direct|tel|telephone)\s*[:\-]|"
    r"(?<![a-zA-Z])(m)\s*[:\-]|(?<![a-zA-Z])(o|d|p)\s*[:\-]"
)

FAX_LABEL_RE = re.compile(r"(?i)\bfax\s*[:\-]")

EXTENSION_RE = re.compile(r"(?i)\b(?:ext\.?|extension|x)\s*[:\-]?\s*(\d{2,6})\b")

US_STATE_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}


def _field(
    value: Any,
    *,
    raw: str | None,
    confidence: float,
    method: str,
    source: str | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "raw": raw,
        "confidence": round(confidence, 2),
        "method": method,
        "source": source,
    }


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not re.match(r"(?i)^https?://", normalized):
        normalized = "https://" + normalized
    return normalized


def _normalize_linkedin(value: str) -> str:
    normalized = _normalize_url(value)
    return normalized.split("?", 1)[0]


def _normalize_phone(raw_number: str, line: str) -> tuple[str | None, str | None]:
    """Returns (e164_value, extension). Falls back to the raw digits with
    no E.164 normalization if `phonenumbers` isn't installed or the number
    doesn't parse -- never fabricates a country code it can't infer."""

    extension_match = EXTENSION_RE.search(line)
    extension = extension_match.group(1) if extension_match else None

    if phonenumbers is None:
        return None, extension

    try:
        parsed = phonenumbers.parse(raw_number, DEFAULT_PHONE_REGION)
    except phonenumbers.NumberParseException:
        return None, extension

    if not phonenumbers.is_valid_number(parsed):
        return None, extension

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), extension


def _extract_phones(content_lines: list[str]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    unlabeled_slot_order = ["phone", "mobile"]

    for line in content_lines:
        if FAX_LABEL_RE.search(line):
            continue

        if phonenumbers is not None:
            matches = list(phonenumbers.PhoneNumberMatcher(line, DEFAULT_PHONE_REGION))
            raw_numbers = [match.raw_string for match in matches]
        else:
            found = PHONE_PATTERN.findall(line)
            raw_numbers = found if isinstance(found, list) else []

        for raw_number in raw_numbers:
            label_match = PHONE_LABEL_RE.search(line[: line.find(raw_number)] or line)
            is_mobile = bool(label_match and (label_match.group(1) or label_match.group(3)))
            is_labeled_phone = bool(label_match and (label_match.group(2) or label_match.group(4)))

            e164_value, extension = _normalize_phone(raw_number, line)
            confidence = 0.97 if (label_match and e164_value) else (
                0.90 if e164_value else 0.55
            )

            entry = _field(
                e164_value,
                raw=raw_number,
                confidence=confidence,
                method="phone_regex" if phonenumbers is None else "phonenumbers",
                source=line.strip(),
            )
            if extension:
                entry["extension"] = extension

            if is_mobile and "mobile" not in fields:
                fields["mobile"] = entry
            elif is_labeled_phone and "phone" not in fields:
                fields["phone"] = entry
            elif not label_match:
                for slot in unlabeled_slot_order:
                    if slot not in fields:
                        fields[slot] = entry
                        break

    return fields


def _extract_name(content_lines: list[str], signoff_line: str | None) -> dict[str, Any] | None:
    if signoff_line:
        inline_match = SIGNOFF_INLINE_NAME_RE.match(signoff_line)
        if inline_match:
            name = inline_match.group("name").strip()
            return _field(name, raw=signoff_line.strip(), confidence=0.90,
                          method="signoff_inline_name", source=signoff_line.strip())

    for line in content_lines[:4]:
        if NAME_LINE_RE.match(line.strip()):
            confidence = 0.90 if signoff_line else 0.75
            method = "signoff_next_line" if signoff_line else "structural_first_line"
            return _field(line.strip(), raw=line.strip(), confidence=confidence,
                          method=method, source=line.strip())

    return None


def _split_name(full_name: str) -> tuple[str | None, str | None, str | None]:
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _extract_title_and_company(
    content_lines: list[str], name_line: str | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    title_field: dict[str, Any] | None = None
    company_field: dict[str, Any] | None = None

    for line in content_lines:
        stripped = line.strip()
        if stripped == (name_line or "").strip():
            continue

        # A real title or company name in a signature is short -- a line
        # this long is a skills/requirements dump that happens to contain
        # a word TITLE_KEYWORDS_RE/COMPANY_SUFFIX_RE also matches (e.g.
        # "...MESSAGING SERVICES EXPERIENCE..." matching "services"), not
        # an actual signature line. Confirmed in production: this is what
        # was turning "MUST HAVE: JAVA, ANGULAR, ..." into a company name.
        if len(stripped) > 80:
            continue

        has_title = bool(TITLE_KEYWORDS_RE.search(stripped))
        has_company = bool(COMPANY_SUFFIX_RE.search(stripped))

        if has_title and has_company:
            split_done = False
            for delimiter in ("|", " - ", ","):
                if delimiter in stripped:
                    left, _, right = stripped.partition(delimiter)
                    left, right = left.strip(), right.strip()
                    left_is_title = bool(TITLE_KEYWORDS_RE.search(left))
                    if title_field is None:
                        title_field = _field(
                            left if left_is_title else right,
                            raw=stripped, confidence=0.85,
                            method="title_company_split", source=stripped,
                        )
                    if company_field is None:
                        company_field = _field(
                            right if left_is_title else left,
                            raw=stripped, confidence=0.85,
                            method="title_company_split", source=stripped,
                        )
                    split_done = True
                    break
            if not split_done:
                # No delimiter (e.g. a company name whose only recognizable
                # word -- "Staffing" -- also matches the title-keyword
                # list). Whichever of title/company is still unset takes
                # this line; don't let an already-set title suppress the
                # company (or vice versa).
                if title_field is None:
                    title_field = _field(stripped, raw=stripped, confidence=0.75,
                                          method="title_keyword", source=stripped)
                elif company_field is None:
                    company_field = _field(stripped, raw=stripped, confidence=0.75,
                                            method="company_suffix", source=stripped)
            continue

        if has_title and title_field is None:
            title_field = _field(stripped, raw=stripped, confidence=0.80,
                                  method="title_keyword", source=stripped)
            continue

        if has_company and company_field is None:
            company_field = _field(stripped, raw=stripped, confidence=0.80,
                                    method="company_suffix", source=stripped)

    return title_field, company_field


@lru_cache(maxsize=1)
def _get_ner_pipeline():
    """Loaded once per process, not once per email -- a fresh spaCy
    pipeline load costs real time (well over what one email's worth of
    processing should spend), lru_cache keeps that cost off the request
    path entirely. Returns None (never raises) if spacy or its
    en_core_web_sm model isn't available, so a missing model degrades to
    "NER fallback finds nothing" rather than breaking signature parsing
    -- the regex-only pass this augments still runs either way.
    """

    if spacy is None:
        return None

    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        return None


def _looks_like_a_person_name(candidate: str) -> bool:
    # A small model with only a few lines of context to work with
    # regularly mistakes recruiting-jargon acronyms (JD, HR) and
    # all-caps tech terms for PERSON when the span it's given wasn't a
    # real signature block to begin with. A real human name is
    # essentially never written in ALL CAPS in a natural signature, so
    # that's the cheapest, safest thing to filter on here -- unlike a
    # company name (ITECSUS, IBM, SAP are all legitimately all-caps),
    # this check is deliberately PERSON-only; see _looks_like_an_org_name.
    return (
        "\n" not in candidate
        and len(candidate) >= 3
        and any(ch.islower() for ch in candidate)
    )


def _looks_like_an_org_name(candidate: str) -> bool:
    # Deliberately more permissive than the PERSON check above -- a real
    # company name is routinely all-caps (ITECSUS, IBM, SAP) or a short
    # acronym, so that signal doesn't help filter noise here the way it
    # does for a person's name. Still reject the cheap, unambiguous junk:
    # nothing spanning multiple lines, nothing that's really an email/URL
    # the model mislabeled, nothing implausibly short.
    return (
        "\n" not in candidate
        and len(candidate) >= 2
        and "@" not in candidate
        and not candidate.lower().startswith(("http://", "https://"))
    )


def _extract_person_org_via_ner(
    content_lines: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Secondary signal for name/company when the regex-only pass above
    finds neither a multi-word name line (NAME_LINE_RE) nor a recognized
    company suffix (COMPANY_SUFFIX_RE) -- a bare single-token name and a
    company with no corporate suffix ("Harry" / "ITECSUS") match neither.
    Only ever called for whichever of the two the caller still hasn't
    found; never asked to overrule a structural match.
    """

    nlp = _get_ner_pipeline()
    if nlp is None or not content_lines:
        return None, None

    text = "\n".join(content_lines)
    doc = nlp(text)

    person: str | None = None
    org: str | None = None

    for ent in doc.ents:
        candidate = ent.text.strip().strip(",")
        if not candidate:
            continue
        if (
            ent.label_ == "PERSON"
            and person is None
            and len(candidate.split()) <= 4
            and _looks_like_a_person_name(candidate)
        ):
            person = candidate
        elif ent.label_ == "ORG" and org is None and _looks_like_an_org_name(candidate):
            org = candidate

    person_field = (
        _field(person, raw=person, confidence=0.65, method="ner_person", source=text)
        if person
        else None
    )
    org_field = (
        _field(org, raw=org, confidence=0.65, method="ner_org", source=text)
        if org
        else None
    )
    return person_field, org_field


def _extract_email(content_lines: list[str]) -> dict[str, Any] | None:
    for line in content_lines:
        match = EMAIL_PATTERN.search(line)
        if match:
            value = _normalize_email(match.group(0))
            return _field(value, raw=match.group(0), confidence=0.98,
                          method="email_regex", source=line.strip())
    return None


def _extract_linkedin(content_lines: list[str]) -> dict[str, Any] | None:
    for line in content_lines:
        match = LINKEDIN_PATTERN.search(line)
        if match:
            value = _normalize_linkedin(match.group(0))
            return _field(value, raw=match.group(0), confidence=0.95,
                          method="linkedin_regex", source=line.strip())
    return None


def _extract_website(content_lines: list[str]) -> dict[str, Any] | None:
    for line in content_lines:
        if LINKEDIN_PATTERN.search(line) or TRACKING_URL_RE.search(line):
            continue
        if SOCIAL_BOILERPLATE_RE.search(line):
            continue
        match = URL_RE.search(line)
        if match:
            value = _normalize_url(match.group(0))
            return _field(value, raw=match.group(0), confidence=0.90,
                          method="url_regex", source=line.strip())
    return None


def _extract_location(content_lines: list[str]) -> dict[str, Any] | None:
    for line in content_lines:
        match = CITY_STATE_RE.search(line)
        if match:
            city, state_abbr, postal = match.group(1).strip(), match.group(2), match.group(3)
            value = f"{city}, {state_abbr}" + (f" {postal}" if postal else "")
            return {
                "address": _field(value, raw=match.group(0), confidence=0.80,
                                   method="city_state_regex", source=line.strip()),
                "city": _field(city, raw=city, confidence=0.80,
                                method="city_state_regex", source=line.strip()),
                "state": _field(state_abbr, raw=state_abbr, confidence=0.80,
                                 method="city_state_regex", source=line.strip()),
                "postal_code": (
                    _field(postal, raw=postal, confidence=0.80,
                           method="city_state_regex", source=line.strip())
                    if postal else None
                ),
            }

        lowered = line.lower()
        for state_name, abbr in US_STATE_TO_ABBR.items():
            if state_name in lowered and re.search(r",\s*" + re.escape(state_name), lowered):
                city_match = re.search(r"([A-Z][a-zA-Z. ]{1,30}),\s*" + re.escape(state_name), line, re.IGNORECASE)
                if city_match:
                    city = city_match.group(1).strip()
                    value = f"{city}, {abbr}"
                    return {
                        "address": _field(value, raw=city_match.group(0), confidence=0.75,
                                           method="city_state_name_regex", source=line.strip()),
                        "city": _field(city, raw=city, confidence=0.75,
                                        method="city_state_name_regex", source=line.strip()),
                        "state": _field(abbr, raw=state_name, confidence=0.75,
                                         method="city_state_name_regex", source=line.strip()),
                        "postal_code": None,
                    }
    return None


# ---------------------------------------------------------------------------
# Signature block detection (Phase 1).
# ---------------------------------------------------------------------------

def _signal_indices(lines: list[str], window_start: int, window_end: int) -> list[int]:
    signal_indices: list[int] = []

    for index in range(window_start, window_end):
        line = lines[index]
        if not line.strip():
            continue
        if (
            EMAIL_PATTERN.search(line)
            or LINKEDIN_PATTERN.search(line)
            or PHONE_LABEL_RE.search(line)
            or PHONE_PATTERN.search(line)
            or TITLE_KEYWORDS_RE.search(line)
            or COMPANY_SUFFIX_RE.search(line)
            or CITY_STATE_RE.search(line)
        ):
            signal_indices.append(index)

    return signal_indices


def _structural_span_in_window(
    lines: list[str], window_start: int, window_end: int, search_end: int
) -> tuple[int, int, str, str | None] | None:
    signal_indices = _signal_indices(lines, window_start, window_end)

    if len(signal_indices) < 2:
        return None

    block_start = signal_indices[0]
    while block_start > window_start and (
        NAME_LINE_RE.match(lines[block_start - 1].strip())
        or not lines[block_start - 1].strip()
    ):
        block_start -= 1
    while block_start < search_end and not lines[block_start].strip():
        block_start += 1

    # A structural block found near the top of a forwarded message is a
    # short "From: Name, Company email@..." line, not a multi-line
    # closing signature -- cap its end at the window instead of running
    # all the way to search_end (which head_start callers only pass a
    # short window for anyway; harmless for the tail-window caller, since
    # window_end == search_end there already).
    block_end = min(window_end, search_end)
    return block_start, block_end, "structural", None


def _detect_signature_span(
    lines: list[str], search_end: int, head_start: int | None = None
) -> tuple[int, int, str, str | None] | None:
    """Returns (start, end, method, signoff_line) over lines[:search_end],
    or None if no signature-like block is found.

    head_start, when given, is tried first: a window right after a
    forwarded-message header block, where a forwarded sender's own
    "From: Name, Company email@..." line typically sits. That's the
    right place to look specifically for a message that's nothing but a
    single forward (see is_pure_forward in parse_email_signature) --
    everywhere else, only the tail-window/signoff-marker checks below
    apply, exactly as before.
    """

    for index in range(search_end):
        if SIGNOFF_RE.match(lines[index]):
            return index, search_end, "signoff_marker", lines[index]

    if head_start is not None:
        head_window = min(15, search_end - head_start)
        span = _structural_span_in_window(
            lines, head_start, head_start + head_window, search_end
        )
        if span is not None:
            return span

    tail_window = min(15, search_end)
    tail_start = search_end - tail_window

    span = _structural_span_in_window(lines, tail_start, search_end, search_end)
    if span is not None:
        return span

    for index in range(tail_start, search_end):
        if SENT_FROM_DEVICE_RE.match(lines[index]):
            return index, search_end, "mobile_signature_marker", None

    return None


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------

def parse_email_signature(
    text: str,
    sender_email: str | None = None,
    include_quoted_history: bool = False,
) -> dict[str, Any]:
    """Detect and extract the sender's signature block from a single email.

    Only the current (top) message is scanned by default -- a signature
    that only reappears inside quoted/forwarded history is ignored (Phase
    6), never enabled without `include_quoted_history=True`.
    """

    body = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = body.split("\n")
    # Quote markers ("> ") are stripped for all matching/extraction below --
    # boundary detection above still runs against raw_lines, since ">" is
    # itself the signal that quoted history has started.
    lines = [_strip_quote_prefix(line) for line in raw_lines]

    boundary = _quote_boundary_index(raw_lines)
    quoted_signature_ignored = False

    # Phase 6's original intent: don't let a signature from ten replies
    # deep in a thread get attributed to the current sender when there's
    # real fresh content above it worth protecting. That protection has
    # nothing to protect when the boundary sits right at the top -- a
    # single "FW:"/forwarded job posting IS its "quoted history" in its
    # entirety, no fresh reply text was ever added above it, and the
    # sender/recruiter info Hermes actually needs lives exactly where this
    # would otherwise stop looking. Only keep the original cutoff when
    # there's substantive text before the boundary to protect.
    lines_before_boundary = (
        sum(1 for line in raw_lines[:boundary] if line.strip())
        if boundary is not None
        else 0
    )
    is_pure_forward = boundary is not None and lines_before_boundary <= 1

    if boundary is not None and not include_quoted_history and not is_pure_forward:
        quoted_text = "\n".join(lines[boundary:])
        if SIGNOFF_RE.search(quoted_text) or EMAIL_PATTERN.search(quoted_text):
            quoted_signature_ignored = True

    search_end = (
        len(lines)
        if include_quoted_history or boundary is None or is_pure_forward
        else boundary
    )

    span = _detect_signature_span(
        lines,
        search_end,
        head_start=_skip_forwarded_header_block(lines, boundary) if is_pure_forward else None,
    )

    if span is None:
        return {
            "parser": PARSER_METADATA,
            "detected": False,
            "raw": "",
            "method": None,
            "contact": {},
            "confidence": 0.0,
            "requires_review": True,
            "sender_email": sender_email.strip().lower() if sender_email else None,
            "signature_email": None,
            "quoted_signature_ignored": quoted_signature_ignored,
            "warnings": ["signature_not_detected"],
        }

    block_start, block_end, method, signoff_line = span
    disclaimer_index = _disclaimer_boundary_index(lines, block_start)
    disclaimer_removed = disclaimer_index is not None and disclaimer_index < block_end
    if disclaimer_removed:
        block_end = disclaimer_index

    signature_raw = "\n".join(lines[block_start:block_end]).strip()

    content_lines = [
        line.strip()
        for line in lines[block_start:block_end]
        if line.strip()
        and not SIGNOFF_RE.match(line)
        and not SENT_FROM_DEVICE_RE.match(line)
        and not SOCIAL_BOILERPLATE_RE.search(line)
        and not TRACKING_URL_RE.search(line)
    ]

    contact: dict[str, Any] = {}
    warnings: list[str] = []

    name_field = _extract_name(content_lines, signoff_line)
    title_field, company_field = _extract_title_and_company(
        content_lines, name_field["value"] if name_field else None
    )

    # Structural extraction needs a title keyword, a recognized company
    # suffix, or 2-4 capitalized words on one line to anchor on -- none
    # of which a bare "Harry" / "ITECSUS" pair gives it. NER only ever
    # fills whichever of the two is still missing; a structural match is
    # never second-guessed. Gated on is_pure_forward specifically: that's
    # the one case where the span's *position* is structurally justified
    # (right after a real forwarded-header block, not a last-resort
    # guess) -- for the generic tail-window fallback the span itself is
    # already a weaker heuristic, and layering NER guesses on top of an
    # untrustworthy span just produces confident-looking nonsense instead
    # of the honest "not detected" that span deserved.
    if is_pure_forward and (name_field is None or company_field is None):
        ner_name_field, ner_company_field = _extract_person_org_via_ner(content_lines)
        if name_field is None:
            name_field = ner_name_field
        if company_field is None:
            company_field = ner_company_field

    if name_field:
        contact["full_name"] = name_field
        first, middle, last = _split_name(name_field["value"])
        if first:
            contact["first_name"] = {**name_field, "value": first}
        if middle:
            contact["middle_name"] = {**name_field, "value": middle}
        if last:
            contact["last_name"] = {**name_field, "value": last}
    else:
        warnings.append("name_not_detected")

    if title_field:
        contact["job_title"] = title_field
    else:
        warnings.append("title_not_detected")

    if company_field:
        contact["company_name"] = company_field
    else:
        warnings.append("company_not_detected")

    email_field = _extract_email(content_lines)
    if email_field:
        contact["email"] = email_field
    else:
        warnings.append("email_not_detected")

    phone_fields = _extract_phones(content_lines)
    contact.update(phone_fields)
    if "phone" not in phone_fields and "mobile" not in phone_fields:
        warnings.append("phone_not_detected")

    linkedin_field = _extract_linkedin(content_lines)
    if linkedin_field:
        contact["linkedin_url"] = linkedin_field

    website_field = _extract_website(content_lines)
    if website_field:
        contact["website"] = website_field

    location_fields = _extract_location(content_lines)
    if location_fields:
        for key, field_value in location_fields.items():
            if field_value:
                contact[key] = field_value

    if method == "mobile_signature_marker" and not any(
        key in contact for key in ("full_name", "email", "phone", "mobile")
    ):
        warnings.append("mobile_signature_marker_only")

    has_name = "full_name" in contact
    has_strong_contact = "email" in contact or "phone" in contact or "mobile" in contact
    has_context = "company_name" in contact or "job_title" in contact
    signal_count = sum([has_name, has_strong_contact, has_context])

    if signal_count >= 3:
        confidence = 0.92
    elif signal_count == 2:
        confidence = 0.70
    elif signal_count == 1:
        confidence = 0.45
    else:
        confidence = 0.0

    sender_email_normalized = sender_email.strip().lower() if sender_email else None
    signature_email_value = contact.get("email", {}).get("value")
    signature_email_out = None
    if signature_email_value and sender_email_normalized and (
        signature_email_value != sender_email_normalized
    ):
        signature_email_out = signature_email_value
        warnings.append("signature_email_differs_from_sender")

    if disclaimer_removed:
        warnings.append("disclaimer_removed")

    return {
        "parser": PARSER_METADATA,
        "detected": True,
        "raw": signature_raw,
        "method": method,
        "contact": contact,
        "confidence": confidence,
        "requires_review": confidence < REQUIRES_REVIEW_THRESHOLD,
        "sender_email": sender_email_normalized,
        "signature_email": signature_email_out,
        "quoted_signature_ignored": quoted_signature_ignored,
        "warnings": warnings,
    }
