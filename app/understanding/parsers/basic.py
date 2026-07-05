import re
from typing import Any

from app.understanding.models import DocumentKind, ExtractedText
from app.understanding.parsers.contact import (
    extract_email,
    extract_linkedin_url,
    extract_phone,
    extract_work_authorization,
)
from app.understanding.parsers.skills import extract_skills
from app.understanding.structured import (
    GenericStructuredData,
    JobDescriptionStructuredData,
    ParserMetadata,
    ResumeStructuredData,
)


def extract_years_experience(text: str) -> int | None:
    patterns = [
        r"(\d{1,2})\+?\s*(?:years|yrs)\s*(?:of\s*)?(?:experience|exp)?",
        r"experience\s*(?:of\s*)?(\d{1,2})\+?\s*(?:years|yrs)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def extract_probable_title(text: str) -> str | None:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    clean_text = re.sub(r"^(need|hiring|looking for|seeking)\s+", "", clean_text, flags=re.IGNORECASE)

    match = re.search(
        r"^([A-Za-z][A-Za-z0-9 .+#/-]{2,80}?)(?:\s+with|\s+having|\s+for|\s+-|,|$)",
        clean_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    title = match.group(1).strip(" .,-")
    title_keywords = [
        "developer",
        "engineer",
        "architect",
        "analyst",
        "administrator",
        "admin",
        "manager",
        "consultant",
        "recruiter",
        "lead",
    ]

    if any(keyword in title.lower() for keyword in title_keywords):
        return title

    return None


def parse_basic_structured_data(
    extracted: ExtractedText,
    document_kind: DocumentKind = "unknown",
) -> dict[str, Any]:
    text = extracted.text or ""
    parser = ParserMetadata(name="basic_local_parser", uses_llm=False)
    skills = extract_skills(text)
    years_experience = extract_years_experience(text)
    probable_title = extract_probable_title(text)

    if document_kind == "resume":
        return ResumeStructuredData(
            skills=skills,
            years_experience=years_experience,
            current_title=probable_title,
            email=extract_email(text),
            phone=extract_phone(text),
            linkedin_url=extract_linkedin_url(text),
            work_authorization=extract_work_authorization(text),
            parser=parser,
        ).model_dump()

    if document_kind == "job_description":
        return JobDescriptionStructuredData(
            skills=skills,
            years_experience=years_experience,
            job_title=probable_title,
            work_authorization=extract_work_authorization(text),
            parser=parser,
        ).model_dump()

    generic_kind = "message" if document_kind == "message" else "unknown"

    return GenericStructuredData(
        document_kind=generic_kind,
        skills=skills,
        years_experience=years_experience,
        parser=parser,
    ).model_dump()
