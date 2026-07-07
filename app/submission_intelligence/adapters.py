from __future__ import annotations

from typing import Any

from app.submission_intelligence.models import (
    SubmissionConsultantSnapshot,
    SubmissionHandoffEvaluationRequest,
    SubmissionIntelligenceRequest,
    SubmissionRequirementSnapshot,
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}

    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {}

    return {}


def _structured_data(value: Any) -> dict[str, Any]:
    data = _as_dict(value)
    structured = data.get("structured_data")

    if isinstance(structured, dict):
        return structured

    return data


def _extracted_text(value: Any) -> str | None:
    data = _as_dict(value)
    extracted = data.get("extracted_text")

    if isinstance(extracted, dict):
        text = extracted.get("text")
        return str(text) if text else None

    return None


def _skill_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        name = value.get("normalized") or value.get("name") or value.get("skill") or value.get("label")
        return str(name).strip() if name else ""

    name = getattr(value, "normalized", None) or getattr(value, "name", None)
    return str(name).strip() if name else ""


def _unique_skill_names(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        name = _skill_name(value)
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            result.append(name)

    return result


def _normalized_skills_or_structured_skills(structured: dict[str, Any]) -> list[str]:
    normalized = structured.get("normalized_skills") or []
    if normalized:
        return _unique_skill_names(normalized)

    return _unique_skill_names(structured.get("skills") or [])


def build_requirement_snapshot_from_understanding(
    job_result: Any,
    job_id: str | None = None,
) -> SubmissionRequirementSnapshot:
    job = _structured_data(job_result)
    all_skills = _normalized_skills_or_structured_skills(job)

    required_skills = _unique_skill_names(job.get("required_skills") or [])
    preferred_skills = _unique_skill_names(job.get("preferred_skills") or [])

    if not required_skills:
        required_skills = all_skills

    return SubmissionRequirementSnapshot(
        job_id=job_id or job.get("job_id"),
        title=job.get("job_title") or job.get("title"),
        client=job.get("client"),
        location=job.get("location"),
        work_authorization=job.get("work_authorization"),
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        raw_source=_extracted_text(job_result),
    )


def build_consultant_snapshot_from_understanding(
    resume_result: Any,
    consultant_id: str | None = None,
    resume_id: str | None = None,
) -> SubmissionConsultantSnapshot:
    resume = _structured_data(resume_result)

    return SubmissionConsultantSnapshot(
        consultant_id=consultant_id or resume.get("consultant_id"),
        name=resume.get("name") or resume.get("candidate_name"),
        location=resume.get("location"),
        work_authorization=resume.get("work_authorization"),
        skills=_normalized_skills_or_structured_skills(resume),
        years_experience=resume.get("years_experience"),
        resume_id=resume_id or resume.get("resume_id"),
    )


def build_taxonomy_context_from_understanding(
    resume_result: Any,
    job_result: Any,
) -> dict[str, Any]:
    resume = _structured_data(resume_result)
    job = _structured_data(job_result)

    return {
        "resume_taxonomy_signals": resume.get("taxonomy_signals") or {},
        "job_taxonomy_signals": job.get("taxonomy_signals") or {},
        "resume_normalized_skills": _unique_skill_names(resume.get("normalized_skills") or []),
        "job_normalized_skills": _unique_skill_names(job.get("normalized_skills") or []),
        "resume_normalized_job_titles": _unique_skill_names(resume.get("normalized_job_titles") or []),
        "job_normalized_job_titles": _unique_skill_names(job.get("normalized_job_titles") or []),
        "source": "hermes-500-handoff-adapter",
    }


def build_match_result_payload(match_result: Any) -> dict[str, Any]:
    data = _as_dict(match_result)

    return {
        "match_score": data.get("match_score"),
        "decision": data.get("decision"),
        "score_breakdown": data.get("score_breakdown") or {},
        "matched_required_skills": data.get("matched_required_skills") or [],
        "missing_required_skills": data.get("missing_required_skills") or [],
        "matched_preferred_skills": data.get("matched_preferred_skills") or [],
        "reasons": data.get("reasons") or [],
        "risks": data.get("risks") or [],
        "recommendation": data.get("recommendation"),
        "matcher_version": data.get("matcher_version"),
        "policy_snapshot": data.get("policy_snapshot") or {},
    }


def build_submission_intelligence_request_from_handoff(
    request: SubmissionHandoffEvaluationRequest,
) -> SubmissionIntelligenceRequest:
    return SubmissionIntelligenceRequest(
        submission_id=request.submission_id,
        current_stage=request.current_stage,
        requirement=build_requirement_snapshot_from_understanding(
            request.job_result,
            job_id=request.job_id,
        ),
        consultant=build_consultant_snapshot_from_understanding(
            request.resume_result,
            consultant_id=request.consultant_id,
            resume_id=request.resume_id,
        ),
        match_result=build_match_result_payload(request.match_result),
        parser_result={
            "resume_result_version": request.resume_result.get("result_version"),
            "job_result_version": request.job_result.get("result_version"),
            "source": "hermes-200-understanding",
        },
        taxonomy_context=build_taxonomy_context_from_understanding(
            request.resume_result,
            request.job_result,
        ),
        existing_submission_keys=request.existing_submission_keys,
    )
