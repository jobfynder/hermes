import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matching.models import ResumeToJobMatchRequest
from app.matching.scorer import evaluate_resume_to_job

CASES = [
    ("submit", ["Python", "FastAPI", "PostgreSQL", "Docker"], ["Python", "FastAPI", "PostgreSQL"], ["Docker"], 6, 5, "H1B", "H1B", "Remote", "Remote"),
    ("review", ["Python", "FastAPI"], ["Python", "FastAPI", "PostgreSQL"], ["Docker"], 4, 5, "H1B", "H1B", "Austin, TX", "Dallas, TX"),
    ("reject", ["React", "CSS"], ["Python", "FastAPI", "PostgreSQL"], ["Docker"], 2, 5, "OPT", "H1B", "Remote", "Dallas, TX"),
]

for expected, resume_skills, required, preferred, resume_years, job_years, resume_auth, job_auth, resume_location, job_location in CASES:
    request = ResumeToJobMatchRequest(
        resume={"skills": resume_skills, "years_experience": resume_years, "work_authorization": resume_auth, "location": resume_location},
        job={"required_skills": required, "preferred_skills": preferred, "years_experience": job_years, "work_authorization": job_auth, "location": job_location},
    )
    result = evaluate_resume_to_job(request)
    assert result.decision == expected, result.model_dump()
    print({"expected": expected, "actual": result.decision, "score": result.match_score, "missing": result.missing_required_skills})

print("HERMES-300 matching scenarios passed")
