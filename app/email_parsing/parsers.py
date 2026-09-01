import re
from typing import Any

from app.email_parsing.signature import SIGNOFF_RE
from app.services.consultant_service import parse_consultant_text
from app.understanding.models import RawDocument
from app.understanding.parsers.basic import extract_probable_title
from app.understanding.service import understand_document


PARSER_METADATA = {
    "name": "hermes_email_deterministic_parser",
    "version": "hermes_email_parser_v1",
    "uses_llm": False,
}


HEADER_ALIASES = {
    "name": "candidate_name",
    "candidate": "candidate_name",
    "candidate name": "candidate_name",
    "consultant": "candidate_name",
    "consultant name": "candidate_name",
    "resource": "candidate_name",
    "resource name": "candidate_name",
    "title": "primary_job_title",
    "job title": "primary_job_title",
    "role": "primary_job_title",
    "technology": "primary_job_title",
    "skill": "primary_skills",
    "skills": "primary_skills",
    "primary skill": "primary_skills",
    "primary skills": "primary_skills",
    "experience": "years_of_experience",
    "exp": "years_of_experience",
    "years": "years_of_experience",
    "total experience": "years_of_experience",
    "location": "current_location",
    "current location": "current_location",
    "visa": "work_authorization",
    "visa status": "work_authorization",
    "work authorization": "work_authorization",
    "work auth": "work_authorization",
    "availability": "availability",
    "available": "availability",
    "available from": "availability",
    "rate": "expected_rate",
    "bill rate": "expected_rate",
    "expected rate": "expected_rate",
    "email": "candidate_email",
    "candidate email": "candidate_email",
    "phone": "candidate_phone",
    "mobile": "candidate_phone",
}


def _extract_subject_line(text: str) -> str | None:
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped[len("subject:"):].strip()
            # Strip a forwarding prefix ("FW:"/"Fwd:"/"RE:", possibly
            # doubled) so the probable-title heuristic below sees the
            # actual subject, not forwarding chrome.
            subject = re.sub(r"(?i)^(?:fw|fwd|re)\s*:\s*", "", subject).strip()
            return subject or None

    return None


def _clean_email_text(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()

    if lines and lines[0].strip().lower().startswith("subject:"):
        lines = lines[1:]

    return "\n".join(lines).strip()


def _normalize_header(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[,;]", value)
        if item.strip()
    ]


def _extract_integer(value: str | None) -> int | None:
    if not value:
        return None

    match = re.search(r"\b(\d{1,2})\b", value)

    if not match:
        return None

    number = int(match.group(1))

    if number > 60:
        return None

    return number


def _extract_labeled_value(text: str, labels: list[str]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)

    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*[:\-]\s*(.+?)\s*$",
        text or "",
    )

    if not match:
        return None

    return match.group(1).strip()


def _is_plausible_job_title(value: str | None) -> bool:
    """A real job title always has at least one letter and more than a
    couple of characters -- rejects the "Position: 1" ordinal-number
    case (see the job_title fallback chain in parse_requirement_email)
    and any similarly-shaped extraction bug before it ever reaches a
    record, let alone the taxonomy candidate queue.
    """
    if not value:
        return False
    stripped = value.strip()
    return len(stripped) >= 3 and bool(re.search(r"[A-Za-z]", stripped))


def _hotlist_record_confidence(record: dict[str, Any]) -> float:
    has_name = bool(record.get("candidate_name"))
    has_role = bool(
        record.get("primary_job_title")
        or record.get("primary_skills")
    )

    if has_name and has_role:
        return 0.92

    if has_name or has_role:
        return 0.62

    return 0.30


def _build_table_hotlist_records(text: str) -> list[dict[str, Any]]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for delimiter in ("|", "\t"):
        for header_index, line in enumerate(lines):
            if delimiter not in line:
                continue

            raw_headers = [
                item.strip()
                for item in line.split(delimiter)
            ]

            mapped_headers = [
                HEADER_ALIASES.get(_normalize_header(item))
                for item in raw_headers
            ]

            recognized_count = sum(
                1
                for item in mapped_headers
                if item is not None
            )

            if recognized_count < 2:
                continue

            records: list[dict[str, Any]] = []

            for row_number, row in enumerate(
                lines[header_index + 1:],
                start=header_index + 2,
            ):
                if delimiter not in row:
                    continue

                values = [
                    item.strip()
                    for item in row.split(delimiter)
                ]

                if len(values) < 2:
                    continue

                raw_record: dict[str, str] = {}

                for index, canonical_header in enumerate(mapped_headers):
                    if not canonical_header:
                        continue

                    if index < len(values):
                        raw_record[canonical_header] = values[index]

                if not raw_record:
                    continue

                record = {
                    "record_type": "consultant_hotlist",
                    "candidate_name": raw_record.get("candidate_name"),
                    "candidate_email": raw_record.get("candidate_email"),
                    "candidate_phone": raw_record.get("candidate_phone"),
                    "primary_job_title": raw_record.get("primary_job_title"),
                    "primary_skills": _split_list(
                        raw_record.get("primary_skills")
                    ),
                    "years_of_experience": _extract_integer(
                        raw_record.get("years_of_experience")
                    ),
                    "current_location": raw_record.get("current_location"),
                    "work_authorization": raw_record.get("work_authorization"),
                    "availability": raw_record.get("availability"),
                    "expected_rate": raw_record.get("expected_rate"),
                    "source_row": row_number,
                    "warnings": [],
                }

                confidence = _hotlist_record_confidence(record)
                record["parse_confidence"] = confidence
                record["requires_review"] = confidence < 0.70

                if not record.get("candidate_name"):
                    record["warnings"].append("candidate_name_missing")

                if not (
                    record.get("primary_job_title")
                    or record.get("primary_skills")
                ):
                    record["warnings"].append(
                        "candidate_title_or_skills_missing"
                    )

                records.append(record)

            if records:
                return records

    return []


def _build_fallback_hotlist_records(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]

    candidate_blocks = [
        block
        for block in blocks
        if re.search(
            r"(?im)^\s*(?:name|candidate|consultant)\s*[:\-]",
            block,
        )
    ]

    if not candidate_blocks:
        candidate_blocks = [text]

    records: list[dict[str, Any]] = []

    for index, block in enumerate(candidate_blocks, start=1):
        parsed = parse_consultant_text(block)

        candidate_name = (
            _extract_labeled_value(
                block,
                ["Name", "Candidate", "Candidate Name", "Consultant"],
            )
            or parsed.get("name")
        )

        record = {
            "record_type": "consultant_hotlist",
            "candidate_name": candidate_name,
            "candidate_email": _extract_labeled_value(
                block,
                ["Email", "Candidate Email"],
            ),
            "candidate_phone": _extract_labeled_value(
                block,
                ["Phone", "Mobile"],
            ),
            "primary_job_title": (
                _extract_labeled_value(
                    block,
                    ["Title", "Job Title", "Role", "Technology"],
                )
                or parsed.get("title")
            ),
            "primary_skills": parsed.get("skills") or [],
            "years_of_experience": parsed.get("experience_years"),
            "current_location": parsed.get("location"),
            "work_authorization": parsed.get("work_authorization"),
            "availability": parsed.get("availability"),
            "expected_rate": parsed.get("rate"),
            "source_block": index,
            "warnings": [],
        }

        confidence = _hotlist_record_confidence(record)
        record["parse_confidence"] = confidence
        record["requires_review"] = confidence < 0.70

        if not record.get("candidate_name"):
            record["warnings"].append("candidate_name_missing")

        if not (
            record.get("primary_job_title")
            or record.get("primary_skills")
        ):
            record["warnings"].append(
                "candidate_title_or_skills_missing"
            )

        records.append(record)

    return records


def parse_hotlist_email(text: str) -> dict[str, Any]:
    clean_text = _clean_email_text(text)

    records = _build_table_hotlist_records(clean_text)

    if not records:
        records = _build_fallback_hotlist_records(clean_text)

    confidence = min(
        (
            float(record.get("parse_confidence", 0.0))
            for record in records
        ),
        default=0.0,
    )

    warnings: list[str] = []

    if not records:
        warnings.append("no_consultants_detected")

    if any(record.get("requires_review") for record in records):
        warnings.append("one_or_more_consultants_require_review")

    return {
        "parser": PARSER_METADATA,
        "document_kind": "hotlist",
        "records": records,
        "record_count": len(records),
        "confidence": confidence,
        "requires_review": (
            not records
            or any(record.get("requires_review") for record in records)
        ),
        "warnings": warnings,
    }


_FORWARDED_HEADER_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:from|sent|to|subject|cc|bcc)\s*:.*$"
)

# Job-board relay boilerplate ("You received this email from X via
# https://jobs.example.com. Please check the email id in the signature to
# reply to the correct email id.") that vendors like jobs.nvoids.com inject
# at the very top of every posting, ahead of the real content. Matched on
# the generic sentence shape rather than a hardcoded domain, since more
# than one relay uses the same phrasing.
_VENDOR_PREAMBLE_LINE_PATTERN = re.compile(
    r"(?im)^\s*you received this email from\b.*$|"
    r"^\s*please check the email id\b.*$"
)

# Corporate email-security-gateway banners (Microsoft Defender, Proofpoint,
# Mimecast, and similar all use near-identical phrasing) injected at the
# very top of any email arriving from outside the recipient's own
# organization. Real recruiter/vendor mail is *always* external by
# definition, so this banner shows up constantly -- left unstripped it
# was exactly the kind of noise the jobs.nvoids.com preamble above turned
# out to be: not part of the posting, but sitting right where a title/
# company-name guess would look first.
_SECURITY_BANNER_LINE_PATTERN = re.compile(
    r"(?im)^\s*\[?external\]?\s*$|"
    r"^\s*external\s+email\b.*$|"
    r"^\s*caution\s*[:\-].*(?:external|outside).*$|"
    r"^\s*this\s+(?:email|message)\s+originated\s+(?:from\s+)?outside\b.*$|"
    r"^\s*you\s+don.t\s+often\s+get\s+email\s+from\b.*$|"
    r"^\s*report\s+this\s+email\b.*$"
)

# Some recruiter-broadcast platforms (prohirespowerhouse.com and
# similar bulk-mail tools) put their unsubscribe/manage-subscription
# masthead at the very TOP of the email, immediately after the From/
# Subject header block -- "Remove/unsubscribe | Update your contact and
# subscribed mailing list(s) | Subscribe to mailing list(s) to receive
# requirements & resumes". _JOB_DESCRIPTION_FOOTER_MARKERS' "unsubscribe"
# marker below assumes an unsubscribe mention sits near the END of the
# text (a real footer) and cuts everything from its first occurrence
# onward -- with this vendor's masthead at the top instead, that cut
# landed a few characters in, truncating the entire real job
# description down to "Remove/" on every single email from this sender
# (confirmed in production). Stripped here, top-of-email only, same as
# the other preamble patterns below, so it never reaches the footer cut.
_BROADCAST_MASTHEAD_LINE_PATTERN = re.compile(
    r"(?im)^\s*remove\s*/\s*unsubscribe\b.*$"
)

# Generic markers for the SEO-keyword-dump / call-to-action tail that
# broadcast job boards commonly append after the real posting. Kept
# short and generic on purpose -- this is not an attempt to strip every
# vendor's specific forwarding boilerplate (e.g. numbered submission
# instructions), since a real JD can legitimately be written as a
# numbered list and blindly stripping those would do more harm than
# good.
_JOB_DESCRIPTION_FOOTER_MARKERS = (
    "view this job online",
    "unsubscribe",
    "keywords:",
)


def _strip_forwarded_header_block(text: str) -> str:
    """Drops a contiguous run of From:/Sent:/To:/Subject: lines, job-board
    relay boilerplate, security-gateway banners, and blank lines at the
    very top of the text -- the standard Outlook forwarded-message
    preamble plus common vendor/gateway noise. Only strips at the top, on
    purpose: a "To:" appearing mid-body is real content, not header noise.
    """
    lines = text.splitlines()
    cursor = 0

    for line in lines:
        if (
            not line.strip()
            or _FORWARDED_HEADER_LINE_PATTERN.match(line)
            or _VENDOR_PREAMBLE_LINE_PATTERN.match(line)
            or _SECURITY_BANNER_LINE_PATTERN.match(line)
            or _BROADCAST_MASTHEAD_LINE_PATTERN.match(line)
        ):
            cursor += 1
            continue
        break

    return "\n".join(lines[cursor:]).strip()


def _strip_job_description_footer(text: str) -> str:
    lowered = text.lower()
    cut_at = len(text)

    for marker in _JOB_DESCRIPTION_FOOTER_MARKERS:
        index = lowered.find(marker)
        if index != -1:
            cut_at = min(cut_at, index)

    # Everything from the sender's own signoff ("--", "Thanks,",
    # "Regards,"...) onward is signature/contact-info/disclaimer noise,
    # never job content -- cut there too, not just at the specific
    # footer marker strings above, which don't cover every vendor's
    # footer shape. Confirmed in production: a posting whose footer
    # never said "Keywords:"/"unsubscribe" was still leaving a trailing
    # "--" and the relay's contact block in job_description.
    signoff = SIGNOFF_RE.search(text)
    if signoff:
        cut_at = min(cut_at, signoff.start())

    return text[:cut_at].strip()


def _strip_known_boilerplate_lines(text: str, extra_boilerplate_lines: frozenset[str] | None) -> str:
    """Removes any line a reviewer has approved as a recurring boilerplate
    pattern (app/understanding/taxonomy/candidates.py:
    get_approved_boilerplate_lines) -- unlike the marker/signoff-based
    cuts above, which only ever trim from a boundary point onward, this
    can remove a single stray line from anywhere in the text.
    """
    if not extra_boilerplate_lines:
        return text

    kept_lines = [
        line
        for line in text.splitlines()
        if re.sub(r"\s+", " ", line.strip().lower()) not in extra_boilerplate_lines
    ]
    return "\n".join(kept_lines)


def _clean_job_description(text: str, extra_boilerplate_lines: frozenset[str] | None = None) -> str:
    cleaned = _strip_forwarded_header_block(text)
    cleaned = _strip_job_description_footer(cleaned)
    cleaned = _strip_known_boilerplate_lines(cleaned, extra_boilerplate_lines)

    # Never hand back an empty description over a merely-unpolished one --
    # an over-eager strip losing everything is worse than leaving noise in.
    return cleaned.strip() or text.strip()


def strip_job_board_boilerplate(text: str) -> str:
    """Public wrapper around the header/footer stripping above, for
    callers outside this module that need vendor boilerplate out of the
    way but aren't building a job_description field specifically (see
    app/channels/service.py:detect_document_kind).

    Real incident: jobs.nvoids.com appends "Free resume and job search
    portal" to the footer of every single posting it relays, including
    pure job REQUIREMENTS with no resume content at all. detect_document_
    kind's keyword-marker fallback classifier used to scan the raw,
    unstripped text, so that one footer phrase's "resume" was enough to
    misclassify an actual job posting as a resume/consultant-profile --
    document_kind="resume" -- which skips the structured job-requirement
    parser entirely (email_parsing.records stays empty, warning
    "unsupported_email_document_kind") and produces exactly the "only
    partial information parsed" symptom reported for this class of
    email. Falls back to header-stripped-only text if the footer strip
    would remove everything, same defensive behavior as
    _clean_job_description.
    """
    cleaned = _strip_forwarded_header_block(text)
    footer_stripped = _strip_job_description_footer(cleaned)
    return footer_stripped.strip() or cleaned.strip()


#: A vendor listing several positions in one email as a numbered list --
#: "1) Power Platform Developer", "2 )Power BI Developer / BI Consultant"
#: -- rather than repeating a "Job Title:" label per posting (the format
#: _split_requirement_sections already handled). Tolerates a space before
#: the closing paren ("2 )") and with/without one after it, both seen in
#: production. Deliberately "\)" only (not ".", not "-") -- a numbered
#: list of REQUIREMENTS inside a single position ("1. 5+ years Java")
#: almost always uses "." or "-", so restricting to ")" keeps this from
#: firing on an ordinary single-position email's own numbered bullets.
_NUMBERED_POSITION_RE = re.compile(r"(?im)^[ \t]*(\d{1,2})[ \t]*\)[ \t]*")


def _numbered_position_sections(text: str) -> list[str] | None:
    matches = list(_NUMBERED_POSITION_RE.finditer(text))

    # Require the list to actually start at 1 -- a stray "12) call
    # backup" line deep in an unrelated single-position email shouldn't
    # be mistaken for the start of a multi-position list.
    if len(matches) < 2 or matches[0].group(1) != "1":
        return None

    # Multi-position emails from job-board relays (jobs.nvoids.com and
    # similar) end the actual listing with a "--"/"Thanks"/"Regards"
    # signoff, followed by boilerplate that repeats the whole subject
    # line and a "Keywords:" dump -- never part of the last position.
    # Without this cap the last section would swallow that entire footer
    # as its own job_description.
    signoff = SIGNOFF_RE.search(text)
    limit = signoff.start() if signoff else len(text)

    matches = [m for m in matches if m.start() < limit]
    if len(matches) < 2:
        return None

    return _sections_from_matches(text, matches, end_limit=limit)


def _sections_from_matches(
    text: str, matches: list[re.Match[str]], end_limit: int | None = None
) -> list[str]:
    end_limit = len(text) if end_limit is None else end_limit
    sections: list[str] = []

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else end_limit
        section = text[start:end].strip()

        if section:
            sections.append(section)

    return sections or [text]


def _split_requirement_sections(text: str) -> list[str]:
    matches = list(
        re.finditer(
            r"(?im)^\s*(?:job title|position|role)\s*[:\-]",
            text,
        )
    )

    if len(matches) > 1:
        return _sections_from_matches(text, matches)

    return _numbered_position_sections(text) or [text]


def _score_requirement_record(
    has_title: bool, has_requirement_evidence: bool, has_company: bool
) -> tuple[float, list[str]]:
    """Shared by the per-section loop in parse_requirement_email and by
    the multi-position fill-forward pass that follows it (a record whose
    `company` got filled in by inheriting another position's value needs
    its confidence/warnings recomputed the same way, not left stale).

    A posting with a clear title and a real skills list used to score
    0.92 -- comfortably above FALLBACK_CONFIDENCE_THRESHOLD (0.70) --
    even when company came back empty, because confidence only ever
    looked at title/skills. That silently skipped the LLM fallback
    (app/email_parsing/llm_fallback.py) on exactly the emails it exists
    for: real-world recruiter/vendor prose ("Hi, this is Francis from
    Indus River Technologies...") that COMPANY_PATTERN's label-based
    regex (app/understanding/parsers/job_description_fields.py) can't
    reasonably generalize across dozens of vendor templates. Measured
    against production: 94 of the last 105 job postings (90%) had a null
    company field, all scoring >=0.92 and never reaching the fallback.
    Capping at 0.65 when company is the only gap routes these into the
    already-enabled, already-credentialed Haiku fallback without
    changing behavior for postings that are actually incomplete on
    title/skills too.
    """
    confidence = (
        0.92
        if has_title and has_requirement_evidence and has_company
        else (
            0.65
            if has_title and has_requirement_evidence
            else (0.62 if has_title or has_requirement_evidence else 0.35)
        )
    )

    warnings: list[str] = []

    if not has_title:
        warnings.append("job_title_missing")

    if not has_requirement_evidence:
        warnings.append("required_skills_not_identified")

    if not has_company:
        warnings.append("company_missing")

    return confidence, warnings


def parse_requirement_email(
    text: str, extra_boilerplate_lines: frozenset[str] | None = None
) -> dict[str, Any]:
    clean_text = _clean_email_text(text)

    if not clean_text:
        return {
            "parser": PARSER_METADATA,
            "document_kind": "job_description",
            "records": [],
            "record_count": 0,
            "confidence": 0.0,
            "requires_review": True,
            "warnings": ["no_requirements_detected"],
        }

    subject_line = _extract_subject_line(text)
    subject_probable_title = (
        extract_probable_title(subject_line) if subject_line else None
    )

    sections = _split_requirement_sections(clean_text)
    records: list[dict[str, Any]] = []
    # Parallel to `records` -- has_title/has_requirement_evidence per
    # record, needed to recompute confidence below if a later fill-
    # forward pass fills in `company` for a record that didn't have it
    # (see _score_requirement_record).
    evidence: list[tuple[bool, bool]] = []

    for index, section in enumerate(sections, start=1):
        understanding = understand_document(
            RawDocument(
                content=section,
                filename=None,
                content_type="text/plain",
                document_kind="job_description",
            )
        )

        structured = understanding.structured_data
        required_skills = [
            item.get("name")
            for item in structured.get("required_skills", [])
            if isinstance(item, dict) and item.get("name")
        ]
        preferred_skills = [
            item.get("name")
            for item in structured.get("preferred_skills", [])
            if isinstance(item, dict) and item.get("name")
        ]

        numbered_marker = _NUMBERED_POSITION_RE.match(section)
        numbered_title = None
        if numbered_marker:
            remainder = section[numbered_marker.end():].splitlines()
            if remainder:
                numbered_title = extract_probable_title(remainder[0].strip())

        # Real production regression: a vendor format lists "Position: 1"
        # (an ordinal, not a title) on its own line, with the actual
        # title one line later under "Title:" -- "Position" being listed
        # as a Job Title alias (below) meant _extract_labeled_value found
        # "Position: 1" first and returned the literal digit "1" as the
        # job title, which then got queued as a taxonomy candidate 25+
        # times over. labeled_title is only trusted if it's plausibly a
        # real title; otherwise "Title:" is tried as its own explicit
        # fallback before giving up on labels entirely.
        labeled_title = _extract_labeled_value(section, ["Job Title", "Position", "Role"])
        if not _is_plausible_job_title(labeled_title):
            labeled_title = _extract_labeled_value(section, ["Title"])
        if not _is_plausible_job_title(labeled_title):
            labeled_title = None

        if not _is_plausible_job_title(numbered_title):
            numbered_title = None

        job_title = (
            labeled_title
            or numbered_title
            or structured.get("job_title")
            # Only the first section inherits the email's own subject as a
            # title guess -- a multi-posting email splitting into several
            # sections shouldn't stamp every one of them with the subject
            # of (at most) the first job it was about.
            or (subject_probable_title if index == 1 else None)
        )

        explicit_required_skills = _extract_labeled_value(
            section,
            [
                "Required Skills",
                "Must Have Skills",
                "Mandatory Skills",
                "Skills Required",
            ],
        )

        body_without_title = re.sub(
            (
                r"(?im)^\\s*(?:job title|position|role)"
                r"\\s*[:\\-]\\s*.+?\\s*$"
            ),
            "",
            section,
            count=1,
        ).strip()

        has_title = bool(job_title)
        has_required_skills = bool(required_skills)
        has_requirement_evidence = bool(
            explicit_required_skills
            or (
                has_required_skills
                and len(body_without_title) >= 40
            )
        )
        has_company = bool(structured.get("company"))
        confidence, warnings = _score_requirement_record(has_title, has_requirement_evidence, has_company)
        evidence.append((has_title, has_requirement_evidence))

        records.append(
            {
                "record_type": "job_requirement",
                "job_title": job_title,
                "job_description": _clean_job_description(section, extra_boilerplate_lines),
                "company": structured.get("company"),
                "linkedin_url": structured.get("linkedin_url"),
                "required_skills": required_skills,
                "preferred_skills": preferred_skills,
                "years_of_experience": structured.get(
                    "years_experience"
                ),
                "location": structured.get("location"),
                "work_authorization": structured.get(
                    "work_authorization"
                ),
                "employment_type": structured.get(
                    "employment_type"
                ),
                "rate_or_salary": structured.get(
                    "rate_or_salary"
                ),
                "source_section": index,
                "parse_confidence": confidence,
                "requires_review": confidence < 0.70,
                "warnings": warnings,
            }
        )

    # A multi-position email often states shared context (location, most
    # often) once for the whole listing rather than repeating it under
    # every numbered item -- a position with no location of its own
    # inherits whichever value another position in the same email did
    # find, rather than being left blank when the information was right
    # there in the email. Never runs for a single-record email: nothing
    # to inherit from, and a solo posting's own missing location should
    # surface as requires_review as it always has.
    if len(records) > 1:
        for field in ("location", "company"):
            shared_value = next(
                (record[field] for record in records if record.get(field)), None
            )
            if shared_value is None:
                continue
            for record, (has_title, has_requirement_evidence) in zip(records, evidence):
                if record.get(field):
                    continue
                record[field] = shared_value
                if field == "company":
                    # Company just went from missing to present -- the
                    # confidence/warnings computed during the loop above
                    # are now stale (see _score_requirement_record).
                    confidence, warnings = _score_requirement_record(
                        has_title, has_requirement_evidence, has_company=True
                    )
                    record["parse_confidence"] = confidence
                    record["requires_review"] = confidence < 0.70
                    record["warnings"] = warnings
                else:
                    record["warnings"] = [w for w in record["warnings"] if w != f"{field}_missing"]

    confidence = min(
        (
            float(record.get("parse_confidence", 0.0))
            for record in records
        ),
        default=0.0,
    )

    return {
        "parser": PARSER_METADATA,
        "document_kind": "job_description",
        "records": records,
        "record_count": len(records),
        "confidence": confidence,
        "requires_review": (
            not records
            or any(record.get("requires_review") for record in records)
        ),
        "warnings": (
            ["one_or_more_requirements_require_review"]
            if any(record.get("requires_review") for record in records)
            else []
        ),
    }


def parse_email_business_records(
    text: str,
    document_kind: str,
    extra_boilerplate_lines: frozenset[str] | None = None,
) -> dict[str, Any]:
    if document_kind == "hotlist":
        return parse_hotlist_email(text)

    if document_kind == "job_description":
        return parse_requirement_email(text, extra_boilerplate_lines)

    return {
        "parser": PARSER_METADATA,
        "document_kind": document_kind,
        "records": [],
        "record_count": 0,
        "confidence": 0.0,
        "requires_review": True,
        "warnings": ["unsupported_email_document_kind"],
    }


#: Both parsers' fallback paths assign a low-but-nonzero confidence to
#: almost any non-empty text (they always emit *a* record, just one
#: flagged requires_review, rather than refusing to guess) -- so two
#: junk-text confidences landing a few hundredths apart is normal noise,
#: not a real signal. CLASSIFICATION_MIN_CONFIDENCE reuses the same 0.70
#: threshold the parsers themselves use for requires_review (see
#: parse_requirement_email/parse_hotlist_email), and
#: CLASSIFICATION_MIN_MARGIN requires the winner to clear the loser by
#: enough that it isn't just noise -- calibrated against this module's own
#: fixtures: a real hotlist/requirement email scores ~0.90 on its own
#: parser vs. ~0.60 on the other (margin ~0.30), while unrelated text
#: scores ~0.30-0.35 on both (margin ~0.05).
CLASSIFICATION_MIN_CONFIDENCE = 0.70
CLASSIFICATION_MIN_MARGIN = 0.15


def classify_email_by_confidence(text: str) -> dict[str, Any] | None:
    """Deterministic hotlist-vs-requirement classification for a mailbox
    that receives both kinds of email with no distinguishing recipient
    address (see app/email_parsing/routing.py -- this is what
    classify_recipient_mailbox() can't resolve when
    HERMES_HOTLIST_MAILBOX and HERMES_REQUIREMENTS_MAILBOX are the same
    address, or when only one is configured).

    Runs both parse_hotlist_email() and parse_requirement_email() and
    keeps whichever scored higher on ITS OWN confidence metric -- both
    already do real structural/content analysis (table-row detection,
    labeled-field extraction, required-skill presence) to arrive at that
    score, so this is strictly more informed than a generic keyword-list
    fallback, while staying fully deterministic (no LLM, same
    PARSER_METADATA["uses_llm"] = False guarantee as everything else in
    this module).

    Returns None -- not a guess -- unless the winner clears BOTH
    CLASSIFICATION_MIN_CONFIDENCE on its own and
    CLASSIFICATION_MIN_MARGIN over the other parser's score: the caller
    should fall back to its own generic classification rather than trust
    a low-confidence or narrow-margin result, since (per the module-level
    comment above) both parsers' fallback paths score *something* for
    almost any input, not just for actual hotlist/requirement content.
    """
    hotlist_result = parse_hotlist_email(text)
    requirement_result = parse_requirement_email(text)

    hotlist_confidence = hotlist_result.get("confidence", 0.0)
    requirement_confidence = requirement_result.get("confidence", 0.0)
    margin = abs(hotlist_confidence - requirement_confidence)

    if margin < CLASSIFICATION_MIN_MARGIN:
        return None

    if hotlist_confidence > requirement_confidence:
        if hotlist_confidence < CLASSIFICATION_MIN_CONFIDENCE:
            return None
        return {"document_kind": "hotlist", "result": hotlist_result}

    if requirement_confidence < CLASSIFICATION_MIN_CONFIDENCE:
        return None
    return {"document_kind": "job_description", "result": requirement_result}
