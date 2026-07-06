from __future__ import annotations

from typing import Any

from app.matching.models import JobMatchInput, ResumeMatchInput, ResumeToJobMatchRequest
from app.understanding.models import UnderstandingResult


def _structured_data(value: Any) -> dict[str, Any]:
    if isinstance(value, UnderstandingResult):
        return value.structured_data
    if isinstance(value, dict):
        return value.get("structured_data", value)
    return {}


def build_resume_to_job_request_from_understanding(
    resume_result: Any,
    job_result: Any,
) -> ResumeToJobMatchRequest:
    resume = _structured_data(resume_result)
    job = _structured_data(job_result)

    return ResumeToJobMatchRequest(
        resume=ResumeMatchInput(
            skills=resume.get("skills") or [],
            years_experience=resume.get("years_experience"),
            work_authorization=resume.get("work_authorization"),
            location=resume.get("location"),
        ),
        job=JobMatchInput(
            skills=job.get("skills") or [],
            required_skills=job.get("required_skills") or [],
            preferred_skills=job.get("preferred_skills") or [],
            years_experience=job.get("years_experience"),
            work_authorization=job.get("work_authorization"),
            location=job.get("location"),
        ),
    )
