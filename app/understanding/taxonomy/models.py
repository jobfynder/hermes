from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TaxonomyConfidence = Literal["high", "medium", "low"]
TaxonomySource = Literal["seed", "manual", "observed", "system"]
ReviewStatus = Literal["approved", "review_required", "rejected"]


class CanonicalSkill(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    skill_type: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    related_skills: list[str] = Field(default_factory=list)
    confidence: TaxonomyConfidence = "high"
    source: TaxonomySource = "seed"


class CanonicalSkillsTaxonomy(BaseModel):
    version: str
    taxonomy_type: Literal["canonical_skills"] = "canonical_skills"
    skills: list[CanonicalSkill]


class SkillAlias(BaseModel):
    alias: str = Field(..., min_length=1)
    canonical_skill: str = Field(..., min_length=1)
    confidence: TaxonomyConfidence = "high"
    source: TaxonomySource = "seed"


class SkillAliasesTaxonomy(BaseModel):
    version: str
    taxonomy_type: Literal["skill_aliases"] = "skill_aliases"
    aliases: list[SkillAlias]


class CanonicalJobTitle(BaseModel):
    title: str = Field(..., min_length=1)
    family: str = Field(..., min_length=1)
    seniority: str | None = None
    aliases: list[str] = Field(default_factory=list)
    related_titles: list[str] = Field(default_factory=list)
    confidence: TaxonomyConfidence = "high"
    source: TaxonomySource = "seed"


class JobTitlesTaxonomy(BaseModel):
    version: str
    taxonomy_type: Literal["job_titles"] = "job_titles"
    titles: list[CanonicalJobTitle]


class TitleAlias(BaseModel):
    alias: str = Field(..., min_length=1)
    canonical_title: str = Field(..., min_length=1)
    confidence: TaxonomyConfidence = "high"
    source: TaxonomySource = "seed"


class TitleAliasesTaxonomy(BaseModel):
    version: str
    taxonomy_type: Literal["title_aliases"] = "title_aliases"
    aliases: list[TitleAlias]


class TaxonomyNormalizationResult(BaseModel):
    input: str
    normalized: str
    matched: bool
    match_type: Literal["canonical", "alias", "unknown"]
    confidence: TaxonomyConfidence
    taxonomy_version: str


class TaxonomySuggestion(BaseModel):
    observed_term: str = Field(..., min_length=1)
    suggestion_type: Literal["skill", "job_title"]
    suggested_canonical_value: str | None = None
    confidence: TaxonomyConfidence = "low"
    status: ReviewStatus = "review_required"
    source_context: str | None = None

class ExtractedTaxonomySignal(BaseModel):
    raw_text: str = Field(..., min_length=1)
    normalized: str = Field(..., min_length=1)
    signal_type: Literal["skill", "job_title"]
    match_type: Literal["canonical", "alias"]
    confidence: TaxonomyConfidence
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., ge=0)


class TaxonomySignalExtractionResult(BaseModel):
    result_version: str = "hermes_taxonomy_signal_extraction_v1"
    taxonomy_versions: dict[str, str] = Field(default_factory=dict)
    skills: list[ExtractedTaxonomySignal] = Field(default_factory=list)
    job_titles: list[ExtractedTaxonomySignal] = Field(default_factory=list)
    unknown_terms: list[TaxonomySuggestion] = Field(default_factory=list)

