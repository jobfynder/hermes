from __future__ import annotations

from typing import Any

from app.matching.models import JobMatchInput, ResumeMatchInput, ResumeToJobMatchRequest
from app.understanding.models import UnderstandingResult
from app.understanding.taxonomy.normalizer import normalize_skill


def _structured_data(value: Any) -> dict[str, Any]:
    if isinstance(value, UnderstandingResult):
        return value.structured_data
    if isinstance(value, dict):
        return value.get("structured_data", value)
    return {}


def _skill_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name") or value.get("skill") or value.get("label")
        return str(name) if name else ""
    name = getattr(value, "name", None)
    return str(name) if name else ""


def _normalize_skill_values(values: list[Any]) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()

    for value in values:
        raw_name = _skill_name(value).strip()
        if not raw_name:
            continue

        normalized = normalize_skill(raw_name)
        name = str(normalized["normalized"]).strip() if normalized.get("normalized") else raw_name

        key = name.lower()
        if key and key not in seen:
            seen.add(key)
            normalized_values.append(name)

    return normalized_values


def _preferred_skills(data: dict[str, Any]) -> list[Any]:
    normalized_skills = data.get("normalized_skills")
    if isinstance(normalized_skills, list) and normalized_skills:
        return _normalize_skill_values(normalized_skills)

    skills = data.get("skills") or []
    if isinstance(skills, list):
        return _normalize_skill_values(skills)

    return []


def _preferred_required_skills(data: dict[str, Any]) -> list[Any]:
    normalized_required = data.get("normalized_required_skills")
    if isinstance(normalized_required, list) and normalized_required:
        return _normalize_skill_values(normalized_required)

    required_skills = data.get("required_skills")
    if isinstance(required_skills, list) and required_skills:
        return _normalize_skill_values(required_skills)

    return _preferred_skills(data)


def _preferred_preferred_skills(data: dict[str, Any]) -> list[Any]:
    normalized_preferred = data.get("normalized_preferred_skills")
    if isinstance(normalized_preferred, list) and normalized_preferred:
        return _normalize_skill_values(normalized_preferred)

    preferred_skills = data.get("preferred_skills")
    if isinstance(preferred_skills, list):
        return _normalize_skill_values(preferred_skills)

    return []


def build_resume_to_job_request_from_understanding(
    resume_result: Any,
    job_result: Any,
) -> ResumeToJobMatchRequest:
    resume = _structured_data(resume_result)
    job = _structured_data(job_result)

    return ResumeToJobMatchRequest(
        resume=ResumeMatchInput(
            skills=_preferred_skills(resume),
            years_experience=resume.get("years_experience"),
            work_authorization=resume.get("work_authorization"),
            location=resume.get("location"),
        ),
        job=JobMatchInput(
            skills=_preferred_skills(job),
            required_skills=_preferred_required_skills(job),
            preferred_skills=_preferred_preferred_skills(job),
            years_experience=job.get("years_experience"),
            work_authorization=job.get("work_authorization"),
            location=job.get("location"),
        ),
    )
