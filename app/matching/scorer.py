from __future__ import annotations

from typing import Any

from app.matching.models import MatchScoreBreakdown, ResumeToJobMatchRequest, ResumeToJobMatchResult
from app.matching.policy import (
    LOCATION_WEIGHT,
    PREFERRED_SKILL_WEIGHT,
    REQUIRED_SKILL_WEIGHT,
    REVIEW_MIN_REQUIRED_SKILL_SCORE,
    REVIEW_SCORE_THRESHOLD,
    SUBMIT_MIN_YEARS_SCORE,
    SUBMIT_SCORE_THRESHOLD,
    WORK_AUTHORIZATION_WEIGHT,
    YEARS_EXPERIENCE_WEIGHT,
    get_active_matching_policy,
)


def _skill_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name") or value.get("skill") or value.get("label")
        return str(name) if name else ""
    name = getattr(value, "name", None)
    return str(name) if name else ""


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _skill_map(values: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name = _skill_name(value).strip()
        normalized = _normalize_text(name)
        if normalized and normalized not in result:
            result[normalized] = name
    return result


def _percent(matched_count: int, total_count: int, default: float = 100.0) -> float:
    if total_count <= 0:
        return default
    return round((matched_count / total_count) * 100, 2)


def _years_score(resume_years: float | None, job_years: float | None) -> float:
    if job_years is None or job_years <= 0:
        return 100.0
    if resume_years is None:
        return 50.0
    if resume_years >= job_years:
        return 100.0
    return round(max(0.0, min(100.0, (resume_years / job_years) * 100)), 2)


def _normalize_auth(value: str | None) -> str:
    text = _normalize_text(value)
    if text in {"h1b", "h 1b", "h1 b"}:
        return "h1b"
    if text in {"gc", "green card", "greencard"}:
        return "green card"
    if text in {"usc", "us citizen", "citizen", "us citizenship"}:
        return "us citizen"
    if text in {"ead", "opt", "cpt"}:
        return text
    return text


def _work_authorization_score(resume_auth: str | None, job_auth: str | None) -> float:
    job = _normalize_auth(job_auth)
    resume = _normalize_auth(resume_auth)
    if not job or job in {"any", "open", "all"}:
        return 100.0
    if not resume:
        return 50.0
    if resume == job or resume in job or job in resume:
        return 100.0
    return 0.0


def _location_score(resume_location: str | None, job_location: str | None) -> float:
    job = _normalize_text(job_location)
    resume = _normalize_text(resume_location)
    if not job:
        return 100.0
    if not resume:
        return 70.0
    if "remote" in job or "remote" in resume:
        return 100.0
    if resume == job or resume in job or job in resume:
        return 100.0
    return 60.0


def evaluate_resume_to_job(request: ResumeToJobMatchRequest) -> ResumeToJobMatchResult:
    resume_skill_map = _skill_map(request.resume.skills)
    required_source = request.job.required_skills or request.job.skills
    required_skill_map = _skill_map(required_source)
    preferred_skill_map = _skill_map(request.job.preferred_skills)

    resume_skills = set(resume_skill_map)
    required_skills = set(required_skill_map)
    preferred_skills = set(preferred_skill_map)

    matched_required_keys = sorted(required_skills & resume_skills)
    missing_required_keys = sorted(required_skills - resume_skills)
    matched_preferred_keys = sorted(preferred_skills & resume_skills)

    matched_required = [required_skill_map[key] for key in matched_required_keys]
    missing_required = [required_skill_map[key] for key in missing_required_keys]
    matched_preferred = [preferred_skill_map[key] for key in matched_preferred_keys]

    required_skill_score = _percent(len(matched_required), len(required_skills))
    preferred_skill_score = _percent(len(matched_preferred), len(preferred_skills), default=0.0)
    years_score = _years_score(request.resume.years_experience, request.job.years_experience)
    work_auth_score = _work_authorization_score(request.resume.work_authorization, request.job.work_authorization)
    location_score = _location_score(request.resume.location, request.job.location)

    match_score = round((
        required_skill_score * REQUIRED_SKILL_WEIGHT +
        preferred_skill_score * PREFERRED_SKILL_WEIGHT +
        years_score * YEARS_EXPERIENCE_WEIGHT +
        work_auth_score * WORK_AUTHORIZATION_WEIGHT +
        location_score * LOCATION_WEIGHT
    ), 2)

    reasons: list[str] = []
    risks: list[str] = []

    if matched_required:
        reasons.append(f"Matched required skills: {', '.join(matched_required)}")
    if not missing_required:
        reasons.append("All required skills are covered")
    if matched_preferred:
        reasons.append(f"Matched preferred skills: {', '.join(matched_preferred)}")
    if years_score >= 100:
        reasons.append("Experience requirement is met")

    if missing_required:
        risks.append(f"Missing required skills: {', '.join(missing_required)}")
    if years_score < 100:
        risks.append("Experience is below or not confirmed")
    if work_auth_score == 50:
        risks.append("Work authorization is not confirmed")
    if work_auth_score == 0:
        risks.append("Work authorization does not match")
    if location_score < 100:
        risks.append("Location is not an exact match")

    if match_score >= SUBMIT_SCORE_THRESHOLD and not missing_required and years_score >= SUBMIT_MIN_YEARS_SCORE and work_auth_score > 0:
        decision = "submit"
        recommendation = "Submit candidate. Core requirements are covered."
    elif match_score >= REVIEW_SCORE_THRESHOLD and required_skill_score >= REVIEW_MIN_REQUIRED_SKILL_SCORE and work_auth_score > 0:
        decision = "review"
        recommendation = "Review manually before submission."
    else:
        decision = "reject"
        recommendation = "Do not submit unless missing details are resolved."

    return ResumeToJobMatchResult(
        match_score=match_score,
        decision=decision,
        score_breakdown=MatchScoreBreakdown(
            required_skill_score=required_skill_score,
            preferred_skill_score=preferred_skill_score,
            years_score=years_score,
            work_authorization_score=work_auth_score,
            location_score=location_score,
        ),
        matched_required_skills=matched_required,
        missing_required_skills=missing_required,
        matched_preferred_skills=matched_preferred,
        reasons=reasons,
        risks=risks,
        recommendation=recommendation,
        policy_snapshot=get_active_matching_policy(),
    )
