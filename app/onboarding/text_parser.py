from typing import Any


KEY_ALIASES = {
    "name": "full_name",
    "full_name": "full_name",
    "company": "company_name",
    "company_name": "company_name",
    "email": "company_email",
    "company_email": "company_email",
    "phone": "phone",
    "linkedin": "linkedin_url",
    "linkedin_url": "linkedin_url",
    "location": "location",
    "focus": "staffing_focus",
    "staffing_focus": "staffing_focus",
    "role": "role",
    "notes": "notes",
}


def parse_key_value_onboarding_text(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        mapped_key = KEY_ALIASES.get(normalized_key)

        if mapped_key and value.strip():
            data[mapped_key] = value.strip()

    return data


def role_from_onboarding_data(data: dict[str, Any], fallback_role: str | None = None) -> str:
    raw_role = (data.get("role") or fallback_role or "unknown").strip().lower()

    if raw_role in {"bsr", "bench sales", "bench_sales", "bench_sales_recruiter"}:
        return "bench_sales"

    if raw_role in {"recruiter", "job recruiter", "technical recruiter"}:
        return "recruiter"

    if raw_role in {"consultant", "candidate"}:
        return "consultant"

    return "unknown"
