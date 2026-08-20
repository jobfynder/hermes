import re


KNOWN_SKILLS = [
    "Java",
    "Spring Boot",
    "AWS",
    "REST API",
    "Python",
    "React",
    "Node.js",
    "PostgreSQL",
    "Docker",
    "Kubernetes",
    "TypeScript",
    "Angular",
    "Azure",
    "GCP",
    "SQL",
    "MongoDB",
]


def extract_name(text: str):
    match = re.search(r"(?:Name[:\-]?\s*)([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text)

    if match:
        return match.group(1).strip()

    return None


def extract_title(text: str):
    match = re.search(
        r"(Senior|Lead|Junior)?\s?[\w\s]+(Developer|Engineer|Architect|Analyst|Consultant)",
        text,
        re.I,
    )

    if match:
        return match.group(0).strip()

    return None


def extract_experience(text: str):
    match = re.search(r"(\d+)\+?\s*(years|yrs)", text, re.I)

    if match:
        return int(match.group(1))

    return None


US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def extract_location(text: str):
    for match in re.finditer(r"([A-Za-z][A-Za-z\s]{1,30}),\s*([A-Z]{2})\b", text):
        city = match.group(1).strip()
        state_code = match.group(2)

        if state_code in US_STATE_CODES:
            return f"{city}, {state_code}"

    return None


def extract_work_authorization(text: str):
    lower_text = text.lower()

    if "h1b" in lower_text:
        return "H1B"

    if "gc" in lower_text or "green card" in lower_text:
        return "GC"

    if "usc" in lower_text or "us citizen" in lower_text:
        return "USC"

    if "opt" in lower_text:
        return "OPT"

    return None


def extract_availability(text: str):
    lower_text = text.lower()

    if "available immediately" in lower_text or "immediate" in lower_text:
        return "Immediate"

    if "2 weeks" in lower_text:
        return "2 Weeks"

    return None


def extract_rate(text: str):
    match = re.search(r"\$?\s?(\d+)\s?/?\s?(hr|hour)", text, re.I)

    if match:
        return f"${match.group(1)}/hr"

    return None


def extract_skills(text: str):
    found = []
    lower_text = text.lower()

    for skill in KNOWN_SKILLS:
        if skill.lower() in lower_text:
            found.append(skill)

    return found


def parse_consultant_text(text: str):
    cleaned_text = text.strip()

    return {
        "name": extract_name(cleaned_text),
        "title": extract_title(cleaned_text),
        "experience_years": extract_experience(cleaned_text),
        "location": extract_location(cleaned_text),
        "work_authorization": extract_work_authorization(cleaned_text),
        "availability": extract_availability(cleaned_text),
        "rate": extract_rate(cleaned_text),
        "skills": extract_skills(cleaned_text),
        "summary": cleaned_text[:300],
    }


def score_consultant_parse_confidence(text: str, parsed: dict) -> tuple[float, list[str]]:
    reasons = []
    score = 1.0

    if len(text.strip()) < 20:
        score -= 0.35
        reasons.append("text_too_short")

    if not parsed.get("name"):
        score -= 0.15
        reasons.append("name_not_found")

    if not parsed.get("title"):
        score -= 0.20
        reasons.append("title_not_found")

    if not parsed.get("skills"):
        score -= 0.25
        reasons.append("no_skills_found")

    if parsed.get("experience_years") is None:
        score -= 0.10
        reasons.append("experience_not_found")

    return max(0.0, round(score, 2)), reasons


def merge_consultant_fallback_fields(parsed: dict, llm_extracted: dict) -> dict:
    merged = dict(parsed)

    if not merged.get("title") and llm_extracted.get("current_title"):
        merged["title"] = llm_extracted["current_title"]

    if not merged.get("skills") and llm_extracted.get("skills"):
        merged["skills"] = llm_extracted["skills"]

    if merged.get("experience_years") is None and llm_extracted.get("years_experience") is not None:
        merged["experience_years"] = llm_extracted["years_experience"]

    if not merged.get("work_authorization") and llm_extracted.get("work_authorization"):
        merged["work_authorization"] = llm_extracted["work_authorization"]

    merged["employers"] = llm_extracted.get("employers", [])
    merged["education"] = llm_extracted.get("education", [])
    merged["certifications"] = llm_extracted.get("certifications", [])

    return merged
