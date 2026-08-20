from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SuggestionType = Literal['skill', 'job_title']
SuggestionStatus = Literal['review_required', 'approved', 'rejected']


class TaxonomySuggestionRecord(BaseModel):
    suggestion_id: str
    suggestion_type: SuggestionType
    observed_term: str
    observed_key: str
    fuzzy_match: dict[str, object] | None = None
    status: SuggestionStatus = 'review_required'
    confidence: str = 'low'
    occurrence_count: int = 1
    first_seen_at: str
    last_seen_at: str
    source_contexts: list[str] = Field(default_factory=list)
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    resolved_canonical_value: str | None = None


class TaxonomySuggestionReviewRequest(BaseModel):
    reviewed_by: str | None = None
    note: str | None = None
    canonical_value: str | None = None
