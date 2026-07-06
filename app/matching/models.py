from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MatchDecision = Literal["submit", "review", "reject"]


class ResumeMatchInput(BaseModel):
    skills: list[Any] = Field(default_factory=list)
    years_experience: float | None = None
    work_authorization: str | None = None
    location: str | None = None


class JobMatchInput(BaseModel):
    skills: list[Any] = Field(default_factory=list)
    required_skills: list[Any] = Field(default_factory=list)
    preferred_skills: list[Any] = Field(default_factory=list)
    years_experience: float | None = None
    work_authorization: str | None = None
    location: str | None = None


class ResumeToJobMatchRequest(BaseModel):
    resume: ResumeMatchInput
    job: JobMatchInput


class MatchScoreBreakdown(BaseModel):
    required_skill_score: float
    preferred_skill_score: float
    years_score: float
    work_authorization_score: float
    location_score: float


class ResumeToJobMatchResult(BaseModel):
    match_score: float
    decision: MatchDecision
    score_breakdown: MatchScoreBreakdown
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendation: str
    matcher_version: str = "basic_local_matcher_v1"
