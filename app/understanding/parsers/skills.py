import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz
import spacy


DEFAULT_SKILLS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Next.js",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "Spring Boot",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Elasticsearch",
    "Typesense",
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Kafka",
    "RabbitMQ",
    "Terraform",
    "Jenkins",
    "GitHub Actions",
    "REST API",
    "GraphQL",
    "NLP",
    "spaCy",
    "Resume Parsing",
    "Job Matching",
]


@lru_cache(maxsize=1)
def get_blank_english_pipeline():
    return spacy.blank("en")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def has_exact_skill_phrase(text: str, skill: str) -> bool:
    normalized_text = normalize_text(text)
    normalized_skill = normalize_text(skill)

    pattern = r"(?<![a-z0-9])" + re.escape(normalized_skill) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def extract_skills(
    text: str,
    taxonomy: list[str] | None = None,
    fuzzy_threshold: int = 94,
) -> list[dict[str, Any]]:
    skills = taxonomy or DEFAULT_SKILLS
    nlp = get_blank_english_pipeline()
    doc = nlp(text or "")

    normalized_text = normalize_text(text)
    token_window_text = " ".join(token.text for token in doc)
    found: dict[str, dict[str, Any]] = {}

    for skill in skills:
        if has_exact_skill_phrase(normalized_text, skill):
            found[skill.lower()] = {
                "name": skill,
                "confidence": 1.0,
                "method": "exact_phrase",
            }
            continue

        score = fuzz.partial_ratio(normalize_text(skill), normalize_text(token_window_text))

        if score >= fuzzy_threshold:
            found[skill.lower()] = {
                "name": skill,
                "confidence": round(score / 100, 2),
                "method": "rapidfuzz_partial_ratio",
            }

    return sorted(
        found.values(),
        key=lambda item: (-item["confidence"], item["name"].lower()),
    )
