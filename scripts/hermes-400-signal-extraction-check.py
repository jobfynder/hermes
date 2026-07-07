#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy.signals import extract_taxonomy_signals


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def names(items: list[dict[str, object]]) -> set[str]:
    return {str(item["normalized"]) for item in items}


def main() -> int:
    print("HERMES-400 signal extraction check started")

    resume_text = """
    Senior Java Engineer with 8 years of experience in Core Java, SpringBoot,
    AWS, Kubernetes/K8s, Docker, Kafka, PostgreSQL, and RESTful API development.
    """

    job_text = """
    Looking for a React UI Developer with JavaScript, ReactJS, TypeScript,
    Next JS, Node, AWS, and GraphQL. SRE exposure is a plus.
    """

    recruiter_text = """
    Bench Sales recruiter / BDM needed for US staffing. Experience with IT recruiter
    workflows, candidate matching, resume parser tools, and GenAI is preferred.
    """

    resume_result = extract_taxonomy_signals(resume_text)
    job_result = extract_taxonomy_signals(job_text)
    recruiter_result = extract_taxonomy_signals(recruiter_text)

    resume_skills = names(resume_result["skills"])
    job_skills = names(job_result["skills"])
    recruiter_skills = names(recruiter_result["skills"])

    resume_titles = names(resume_result["job_titles"])
    job_titles = names(job_result["job_titles"])
    recruiter_titles = names(recruiter_result["job_titles"])

    require("Java" in resume_skills, "Core Java did not extract as Java")
    require("Spring Boot" in resume_skills, "SpringBoot did not extract as Spring Boot")
    require("AWS" in resume_skills, "AWS was not extracted")
    require("Kubernetes" in resume_skills, "K8s/Kubernetes was not extracted")
    require("PostgreSQL" in resume_skills, "PostgreSQL was not extracted")
    require("REST API" in resume_skills, "RESTful API did not extract as REST API")
    require("Senior Java Developer" in resume_titles, "Senior Java Engineer title did not normalize")

    require("React" in job_skills, "ReactJS did not extract as React")
    require("JavaScript" in job_skills, "JavaScript was not extracted")
    require("TypeScript" in job_skills, "TypeScript was not extracted")
    require("Next.js" in job_skills, "Next JS did not extract as Next.js")
    require("Node.js" in job_skills, "Node did not extract as Node.js")
    require("Frontend React Developer" in job_titles, "React UI Developer title did not normalize")
    require("Site Reliability Engineer" in job_titles, "SRE title did not normalize")

    require("Job Matching" in recruiter_skills, "candidate matching did not extract as Job Matching")
    require("Resume Parsing" in recruiter_skills, "resume parser did not extract as Resume Parsing")
    require("Generative AI" in recruiter_skills, "GenAI did not extract as Generative AI")
    require("Bench Sales Recruiter" in recruiter_titles, "Bench Sales recruiter title did not normalize")
    require("Business Development Manager" in recruiter_titles, "BDM did not normalize")

    print("OK: resume taxonomy signals extracted")
    print("OK: job taxonomy signals extracted")
    print("OK: recruiter taxonomy signals extracted")
    print("HERMES-400 signal extraction check PASSED")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-400 signal extraction check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
