import re
from typing import Any

from app.understanding.parsers.contact import extract_phone

SECTION_ALIASES = {
    "education": "education",
    "skills": "skills",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "projects": "projects",
    "achievements": "achievements",
    "certifications": "certifications",
    "certificates": "certifications",
    "summary": "summary",
    "objective": "summary",
    "profile": "summary",
}

SECTION_HEADER = re.compile(
    r"^(Education|Skills|Experience|Work Experience|Professional Experience|"
    r"Projects|Achievements|Certifications|Certificates|Summary|Objective|Profile)\s*$",
    flags=re.IGNORECASE,
)

PRIMARY_BULLET = re.compile(r"^[•●▪*]\s+")
SUB_BULLET = re.compile(r"^[◦\-–—]\s+")
ANY_BULLET = re.compile(r"^[•●▪*◦\-–—]\s+")

MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
DATE_RANGE = re.compile(
    rf"({MONTHS}\s+\d{{4}}\s*[-–—]\s*(?:Present|{MONTHS}\s+\d{{4}}|\d{{4}})"
    rf"|\d{{4}}\s*[-–—]\s*(?:Present|\d{{4}}))",
    flags=re.IGNORECASE,
)

NAME_LOCATION = re.compile(
    r"^(.+?)\s+([A-Z][A-Za-z.]+,\s*[A-Z][A-Za-z.]+)$"
)
WORKPLACE_OR_COUNTRY = (
    r"(?:Onsite|On-site|Remote|Hybrid|India|USA|US|UK|UAE|"
    r"Canada|Germany|Singapore|Australia)"
)
LOCATION_TAIL = re.compile(
    rf"\s+((?:[A-Z][A-Za-z.]+\s+){{0,2}}[A-Z][A-Za-z.]+,\s*"
    rf"{WORKPLACE_OR_COUNTRY}\b.*)$",
    flags=re.IGNORECASE,
)
CITY_COUNTRY_TAIL = re.compile(
    r"\s+([A-Z][A-Za-z.]+(?:,\s*[A-Z][A-Za-z.]+)+)\s*$"
)
CITY_PREFIXES = {
    "san",
    "santa",
    "los",
    "new",
    "fort",
    "saint",
    "st",
    "north",
    "south",
    "east",
    "west",
    "hong",
    "kuala",
    "abu",
}
CERT_HINT = re.compile(
    r"certified|certification|certificate|\b[A-Z]{2,}-\d+\b",
    flags=re.IGNORECASE,
)


def _split_name_location(header_line: str) -> tuple[str | None, str | None]:
    line = header_line.strip()
    if not line:
        return None, None

    if "|" in line:
        left, right = line.split("|", 1)
        name = left.strip() or None
        location = right.strip() or None
        return name, location

    match = NAME_LOCATION.match(line)
    if match:
        name = match.group(1).strip()
        location = match.group(2).strip()
        if name and not re.search(r"\d|@", name) and 1 <= len(name.split()) <= 5:
            return name, location

    if 1 <= len(line.split()) <= 5 and not re.search(r"\d|@", line):
        return line, None

    return None, None


def split_resume_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for line in (text or "").splitlines():
        stripped = line.strip()
        alias = SECTION_ALIASES.get(stripped.lower())
        if alias and SECTION_HEADER.match(stripped):
            current = alias
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
        if any(line.strip() for line in lines)
    }


def _overlapping_matches(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    start = 0
    while start < len(text):
        found = pattern.search(text, start)
        if not found:
            break
        matches.append(found)
        start = found.start() + 1
    return matches


def _best_location_match(text: str) -> re.Match[str] | None:
    matches = _overlapping_matches(LOCATION_TAIL, text)
    if not matches:
        return CITY_COUNTRY_TAIL.search(text)

    prefixed = [
        match
        for match in matches
        if match.group(1).split(",", 1)[0].split()[0].lower() in CITY_PREFIXES
    ]
    return (prefixed or matches)[-1]


def _split_company_location(line: str) -> tuple[str, str | None]:
    cleaned = ANY_BULLET.sub("", line).strip()
    match = _best_location_match(cleaned)
    if not match:
        return cleaned, None
    return cleaned[: match.start()].strip(), match.group(1).strip()


def _parse_title_dates(line: str) -> tuple[str | None, str | None, str | None]:
    date_match = DATE_RANGE.search(line)
    if not date_match:
        title = line.strip(" |,-") or None
        return title, None, None

    title = line[: date_match.start()].strip(" |,-") or None
    parts = re.split(r"\s*[-–—]\s*", date_match.group(0), maxsplit=1)
    start = parts[0].strip() if parts else None
    end = parts[1].strip() if len(parts) > 1 else None
    return title, start, end


def _year_from_date(value: str | None) -> str | None:
    if not value or value.lower() == "present":
        return None
    years = re.findall(r"\d{4}", value)
    return years[-1] if years else None


def parse_experience_section(section: str) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in (section or "").splitlines() if line.strip()]
    jobs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    bullets: list[str] = []

    def flush() -> None:
        nonlocal current, bullets
        if current:
            if bullets:
                current["description"] = "\n".join(bullets)
            jobs.append(current)
        current = None
        bullets = []

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        is_primary = bool(PRIMARY_BULLET.match(line)) and not SUB_BULLET.match(line)

        if is_primary:
            flush()
            company, location = _split_company_location(line)
            title, start, end = None, None, None
            if index + 1 < len(lines) and DATE_RANGE.search(lines[index + 1]):
                title, start, end = _parse_title_dates(lines[index + 1].strip())
                index += 1
            current = {
                "company": company,
                "title": title,
                "jobTitle": title,
                "startDate": start,
                "endDate": end,
                "location": location,
            }
        elif current and SUB_BULLET.match(line):
            bullets.append(SUB_BULLET.sub("", line).strip())
        elif current and DATE_RANGE.search(line) and not current.get("title"):
            title, start, end = _parse_title_dates(line)
            current["title"] = title
            current["jobTitle"] = title
            current["startDate"] = start
            current["endDate"] = end
        index += 1

    flush()
    return jobs


def parse_education_section(section: str) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in (section or "").splitlines() if line.strip()]
    items: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not PRIMARY_BULLET.match(line):
            index += 1
            continue

        institution, location = _split_company_location(line)
        degree, field, start, end = None, None, None, None

        if index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            looks_like_degree = bool(
                DATE_RANGE.search(next_line)
                or re.search(
                    r"bachelor|master|b\.?tech|m\.?tech|b\.?e\.|m\.?s\.|mba|phd|diploma|gpa",
                    next_line,
                    flags=re.IGNORECASE,
                )
            )
            if looks_like_degree:
                degree_line = next_line
                date_match = DATE_RANGE.search(degree_line)
                if date_match:
                    degree = degree_line[: date_match.start()].strip(" ;,|-")
                    parts = re.split(r"\s*[-–—]\s*", date_match.group(0), maxsplit=1)
                    start = parts[0].strip() if parts else None
                    end = parts[1].strip() if len(parts) > 1 else None
                else:
                    degree = degree_line
                if degree and ";" in degree:
                    degree = degree.split(";", 1)[0].strip()
                if degree and " - " in degree:
                    left, right = degree.split(" - ", 1)
                    degree, field = left.strip(), right.strip()
                index += 1

        items.append(
            {
                "institution": institution,
                "school": institution,
                "degree": degree,
                "field": field,
                "year": _year_from_date(end) or _year_from_date(start),
                "startDate": start,
                "endDate": end,
                "location": location,
            }
        )
        index += 1

    return items


def parse_certification_sections(*sections: str) -> list[str]:
    certs: list[str] = []
    for section in sections:
        if not section:
            continue
        for line in section.splitlines():
            cleaned = ANY_BULLET.sub("", line).strip()
            if cleaned and CERT_HINT.search(cleaned):
                certs.append(cleaned)
    return list(dict.fromkeys(certs))


def extract_resume_sections(text: str) -> dict[str, Any]:
    sections = split_resume_sections(text)
    header = sections.get("header", "")
    first_line = next((line.strip() for line in header.splitlines() if line.strip()), "")
    name, location = _split_name_location(first_line)
    experience = parse_experience_section(sections.get("experience", ""))
    education = parse_education_section(sections.get("education", ""))
    certifications = parse_certification_sections(
        sections.get("certifications", ""),
        sections.get("achievements", ""),
    )
    current_title = experience[0].get("title") if experience else None

    return {
        "name": name,
        "location": location,
        "phone": extract_phone(text),
        "current_title": current_title,
        "summary": sections.get("summary") or None,
        "experience": experience,
        "education": education,
        "certifications": certifications,
    }
