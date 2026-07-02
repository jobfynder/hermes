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


def extract_location(text: str):
    match = re.search(r"([A-Za-z\s]+,\s*[A-Z]{2})", text)

    if match:
        return match.group(1).strip()

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