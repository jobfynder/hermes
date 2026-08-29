from typing import Literal

from pydantic import BaseModel, Field


class ParsedSkill(BaseModel):
    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    method: str


class ParserMetadata(BaseModel):
    name: str
    uses_llm: bool = False
    schema_version: str = "hermes_understanding_v1"


class ResumeStructuredData(BaseModel):
    document_kind: Literal["resume"] = "resume"
    skills: list[ParsedSkill] = Field(default_factory=list)
    years_experience: int | None = None
    current_title: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    work_authorization: str | None = None
    parser: ParserMetadata


class JobDescriptionStructuredData(BaseModel):
    document_kind: Literal["job_description"] = "job_description"
    skills: list[ParsedSkill] = Field(default_factory=list)
    required_skills: list[ParsedSkill] = Field(default_factory=list)
    preferred_skills: list[ParsedSkill] = Field(default_factory=list)
    years_experience: int | None = None
    job_title: str | None = None
    location: str | None = None
    work_authorization: str | None = None
    employment_type: str | None = None
    rate_or_salary: str | None = None
    company: str | None = None
    parser: ParserMetadata


class GenericStructuredData(BaseModel):
    document_kind: Literal["message", "unknown"] = "unknown"
    skills: list[ParsedSkill] = Field(default_factory=list)
    years_experience: int | None = None
    parser: ParserMetadata
