from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SkillContext = Literal["required", "preferred", "mentioned", "excluded"]
MatchType = Literal["canonical", "alias", "normalized", "fuzzy", "unknown"]


class ResolveBatchRequest(BaseModel):
    terms: list[str] = Field(..., min_length=1, max_length=100)


class RequirementIntelligenceRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)
    include_unknown_terms: bool = False


class SkillRelationshipDTO(BaseModel):
    type: str
    skill_id: str
    name: str


class SkillCardDTO(BaseModel):
    skill_id: str
    canonical_name: str
    matched_term: str | None = None
    match_type: MatchType | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    category: str
    subcategory: str | None = None
    definition: str | None = None
    recruiter_explanation: str | None = None
    aliases: list[str] = Field(default_factory=list)
    relationships: list[SkillRelationshipDTO] = Field(default_factory=list)
    related_roles: list[str] = Field(default_factory=list)
    taxonomy_version: str


class ResolvedSkillDTO(BaseModel):
    input: str
    matched: bool
    skill_id: str | None = None
    canonical_name: str | None = None
    matched_term: str | None = None
    match_type: MatchType
    confidence: float = Field(ge=0, le=1)
    taxonomy_version: str


class ClassifiedSkillDTO(BaseModel):
    skill_id: str
    canonical_name: str
    matched_term: str
    confidence: float = Field(ge=0, le=1)
    context: SkillContext
    category: str
    subcategory: str | None = None


class ResolveBatchResponse(BaseModel):
    result_version: str = "hermes_skill_intelligence_resolve_v1"
    taxonomy_version: str
    results: list[ResolvedSkillDTO]


class RequirementIntelligenceResponse(BaseModel):
    result_version: str = "hermes_requirement_skill_intelligence_v1"
    taxonomy_version: str
    skills: dict[str, list[ClassifiedSkillDTO]]
    stack: dict[str, list[ClassifiedSkillDTO]]
    unknown_terms: list[str] = Field(default_factory=list)
