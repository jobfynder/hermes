import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matching.adapters import build_resume_to_job_request_from_understanding
from app.matching.scorer import evaluate_resume_to_job

resume_result = {"structured_data": {"skills": [{"name": "Python"}, {"name": "FastAPI"}, {"name": "PostgreSQL"}, {"name": "Docker"}], "years_experience": 6, "work_authorization": "H1B", "location": "Remote"}}
job_result = {"structured_data": {"required_skills": [{"name": "Python"}, {"name": "FastAPI"}, {"name": "PostgreSQL"}], "preferred_skills": [{"name": "Docker"}, {"name": "Kubernetes"}], "years_experience": 5, "work_authorization": "H1B", "location": "Remote"}}

request = build_resume_to_job_request_from_understanding(resume_result, job_result)
result = evaluate_resume_to_job(request)

assert result.decision == "submit", result.model_dump()
assert result.match_score >= 90, result.model_dump()
assert "Python" in result.matched_required_skills, result.model_dump()
assert "Docker" in result.matched_preferred_skills, result.model_dump()

print({"adapter": "ok", "decision": result.decision, "score": result.match_score, "matcher_version": result.matcher_version})
