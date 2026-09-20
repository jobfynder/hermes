"""Matching compares skills by canonical identity, the same identity the glossary uses."""

from __future__ import annotations

import unittest

from app.matching.models import ResumeToJobMatchRequest
from app.matching.scorer import evaluate_resume_to_job


def _match(resume_skills, required, preferred=()):
    return evaluate_resume_to_job(
        ResumeToJobMatchRequest(
            resume={"skills": list(resume_skills), "years_experience": 6, "work_authorization": "USC", "location": "Dallas, TX"},
            job={
                "required_skills": list(required),
                "preferred_skills": list(preferred),
                "years_experience": 5,
                "work_authorization": "USC",
                "location": "Dallas, TX",
            },
        )
    )


class CanonicalIdentityMatchingTests(unittest.TestCase):
    def test_an_alias_on_the_resume_matches_the_canonical_name_on_the_job(self):
        cases = [("K8s", "Kubernetes"), ("Postgres", "PostgreSQL"), ("ReactJS", "React"), ("SpringBoot", "Spring Boot")]
        for resume_spelling, job_spelling in cases:
            with self.subTest(resume=resume_spelling, job=job_spelling):
                result = _match([resume_spelling], [job_spelling])
                self.assertEqual(result.missing_required_skills, [])
                self.assertEqual(result.matched_required_skills, [job_spelling])
                self.assertEqual(result.score_breakdown.required_skill_score, 100.0)

    def test_an_alias_on_the_job_matches_the_canonical_name_on_the_resume(self):
        result = _match(["Kubernetes"], ["K8s"])
        self.assertEqual(result.missing_required_skills, [])
        self.assertEqual(result.matched_required_skills, ["K8s"])

    def test_preferred_skills_use_the_same_identity(self):
        result = _match(["Java", "K8s"], ["Java"], preferred=["Kubernetes"])
        self.assertEqual(result.matched_preferred_skills, ["Kubernetes"])

    def test_the_result_keeps_the_spelling_the_job_used(self):
        result = _match(["Postgres"], ["PostgreSQL"])
        self.assertEqual(result.matched_required_skills, ["PostgreSQL"])

    def test_related_skills_are_not_equivalent(self):
        result = _match(["Docker"], ["Kubernetes"])
        self.assertEqual(result.missing_required_skills, ["Kubernetes"])
        self.assertEqual(result.score_breakdown.required_skill_score, 0.0)

    def test_unknown_terms_still_match_only_by_their_own_text(self):
        same = _match(["Zorblaxian Framework"], ["zorblaxian framework"])
        self.assertEqual(same.missing_required_skills, [])
        different = _match(["Zorblaxian Framework"], ["Quuxian Framework"])
        self.assertEqual(different.missing_required_skills, ["Quuxian Framework"])

    def test_two_spellings_of_one_skill_on_the_job_count_once(self):
        result = _match(["Kubernetes"], ["Kubernetes", "K8s"])
        self.assertEqual(result.matched_required_skills, ["Kubernetes"])
        self.assertEqual(result.score_breakdown.required_skill_score, 100.0)

    def test_dict_shaped_skills_are_canonicalized_too(self):
        request = ResumeToJobMatchRequest(
            resume={"skills": [{"name": "K8s"}], "years_experience": 6, "work_authorization": "USC", "location": "Dallas, TX"},
            job={"required_skills": [{"name": "Kubernetes"}], "years_experience": 5, "work_authorization": "USC", "location": "Dallas, TX"},
        )
        self.assertEqual(evaluate_resume_to_job(request).missing_required_skills, [])


if __name__ == "__main__":
    unittest.main()
