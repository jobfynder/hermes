import re


LOCATION_PATTERN = re.compile(
    r"(?:location|loc)\s*[:\-]\s*([A-Za-z0-9 ,./\-]+)",
    flags=re.IGNORECASE,
)

RATE_PATTERN = re.compile(
    r"(?:rate|salary|pay)\s*[:\-]?\s*(\$?\d{2,4}(?:\s*[-–]\s*\$?\d{2,4})?\s*(?:/hr|per hour|hourly|hr|k|K|per year|yearly|annually)?)",
    flags=re.IGNORECASE,
)

INLINE_RATE_PATTERN = re.compile(
    r"(\$?\d{2,4}(?:\s*[-–]\s*\$?\d{2,4})?\s*(?:/hr|per hour|hourly|hr|k|K|per year|yearly|annually))",
    flags=re.IGNORECASE,
)


def clean_field(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = re.split(r"[\n\r;|]", value.strip())[0].strip(" .,-")

    return cleaned or None


def extract_location(text: str) -> str | None:
    clean_text = text or ""

    if re.search(r"\bremote\b", clean_text, flags=re.IGNORECASE):
        return "Remote"

    if re.search(r"\bhybrid\b", clean_text, flags=re.IGNORECASE):
        match = LOCATION_PATTERN.search(clean_text)
        location = clean_field(match.group(1)) if match else None
        return f"Hybrid - {location}" if location else "Hybrid"

    match = LOCATION_PATTERN.search(clean_text)

    if match:
        return clean_field(match.group(1))

    city_state_match = re.search(
        r"\b([A-Z][A-Za-z .]+,\s*[A-Z]{2})\b",
        clean_text,
    )

    return clean_field(city_state_match.group(1)) if city_state_match else None


def extract_employment_type(text: str) -> str | None:
    clean_text = text or ""

    checks = [
        ("Contract to Hire", r"\b(?:contract to hire|c2h|contract-to-hire)\b"),
        ("Contract", r"\b(?:contract|corp to corp|c2c|1099)\b"),
        ("W2", r"\b(?:w2|w-2)\b"),
        ("Full-time", r"\b(?:full time|full-time|permanent|perm)\b"),
        ("Part-time", r"\b(?:part time|part-time)\b"),
    ]

    for label, pattern in checks:
        if re.search(pattern, clean_text, flags=re.IGNORECASE):
            return label

    return None


def extract_rate_or_salary(text: str) -> str | None:
    clean_text = text or ""

    match = RATE_PATTERN.search(clean_text)

    if match:
        return clean_field(match.group(1))

    match = INLINE_RATE_PATTERN.search(clean_text)

    return clean_field(match.group(1)) if match else None
