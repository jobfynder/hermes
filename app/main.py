from fastapi import FastAPI
from pydantic import BaseModel
import re

app = FastAPI(title="Hermes", version="0.1.0")


class JobParseRequest(BaseModel):
    text: str


KNOWN_SKILLS = [
    "Java", "Spring Boot", "AWS", "REST API", "Python", "React",
    "Node.js", "PostgreSQL", "Docker", "Kubernetes", "TypeScript",
    "Angular", "Azure", "GCP", "SQL", "MongoDB"
]


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Hermes",
        "version": "0.1.0"
    }


def extract_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    if len(first_line) <= 80:
        return first_line
    match = re.search(r"(Senior|Lead|Junior)?\s?[\w\s]+(Developer|Engineer|Architect|Analyst|Consultant)", text, re.I)
    return match.group(0).strip() if match else "Unknown"


def extract_skills(text: str) -> list[str]:
    found = []
    lower_text = text.lower()
    for skill in KNOWN_SKILLS:
        if skill.lower() in lower_text:
            found.append(skill)
    return found


def extract_location(text: str):
    match = re.search(r"Location[:\-]?\s*([A-Za-z\s]+,\s*[A-Z]{2})", text, re.I)
    return match.group(1).strip() if match else None


def extract_employment_type(text: str):
    lower_text = text.lower()
    if "contract" in lower_text:
        return "Contract"
    if "full time" in lower_text or "full-time" in lower_text:
        return "Full-time"
    if "part time" in lower_text or "part-time" in lower_text:
        return "Part-time"
    return None


@app.post("/v1/jobs/parse")
def parse_job(request: JobParseRequest):
    text = request.text.strip()

    return {
        "success": True,
        "data": {
            "title": extract_title(text),
            "summary": text[:300],
            "skills": extract_skills(text),
            "location": extract_location(text),
            "employment_type": extract_employment_type(text)
        }
    }