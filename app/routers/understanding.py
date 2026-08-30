from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.security.rbac import require_permission
from app.understanding.extractors.local_file import extract_local_file
from app.understanding.models import DocumentKind, RawDocument, UnderstandingResult
from app.understanding.service import build_understanding_result, understand_document
from app.understanding.taxonomy.candidates import get_skill_usage_stats
from app.understanding.taxonomy.loader import (
    load_canonical_skills_taxonomy,
    load_job_titles_taxonomy,
    load_skill_aliases_taxonomy,
    load_skills_taxonomy,
    load_title_aliases_taxonomy,
)
from app.understanding.taxonomy.normalizer import normalize_job_title, normalize_skill
from app.understanding.taxonomy.signals import extract_taxonomy_signals
from app.understanding.taxonomy.suggestions import build_taxonomy_suggestions
from app.understanding.taxonomy.versioning import build_taxonomy_snapshot

router = APIRouter(prefix="/understanding", tags=["Understanding"])


class TaxonomyNormalizeRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)


class TaxonomySignalExtractionRequest(BaseModel):
    text: str = Field(..., min_length=1)


class TaxonomySuggestionRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    source_context: str | None = None


@router.post("/parse-text", response_model=UnderstandingResult)
def parse_text(
    document: RawDocument,
    user: dict = Depends(require_permission("understanding:parse")),
) -> UnderstandingResult:
    return understand_document(document)


@router.post("/parse-file", response_model=UnderstandingResult)
async def parse_file(
    file: UploadFile = File(...),
    document_kind: DocumentKind = Form("unknown"),
    user: dict = Depends(require_permission("understanding:parse")),
) -> UnderstandingResult:
    suffix = Path(file.filename or "uploaded.txt").suffix or ".txt"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(await file.read())

    try:
        extracted = extract_local_file(temp_path)
        extracted.filename = file.filename
        extracted.content_type = file.content_type

        return build_understanding_result(
            extracted=extracted,
            document_kind=document_kind,
        )
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/taxonomy/skills")
def get_skills_taxonomy(user: dict = Depends(require_permission("understanding:read"))):
    return load_skills_taxonomy()


@router.get("/taxonomy/skills/canonical")
def get_canonical_skills_taxonomy(user: dict = Depends(require_permission("understanding:read"))):
    return load_canonical_skills_taxonomy()


@router.get("/taxonomy/skills/browse")
def browse_canonical_skills(user: dict = Depends(require_permission("understanding:read"))) -> list[dict]:
    """Canonical skills merged with real usage stats (app/understanding/
    taxonomy/candidates.py: record_skill_usage) -- what the frontend
    taxonomy browse page reads. A separate endpoint from /taxonomy/
    skills/canonical rather than changing that one's response shape,
    since it's an existing contract other callers may already depend on.
    """
    taxonomy = load_canonical_skills_taxonomy()
    usage = get_skill_usage_stats()

    return [
        {
            **entry,
            "times_seen": usage.get(entry.get("name"), {}).get("times_seen", 0),
            "last_seen_at": usage.get(entry.get("name"), {}).get("last_seen_at"),
        }
        for entry in taxonomy.get("skills", [])
    ]


@router.get("/taxonomy/skills/aliases")
def get_skill_aliases_taxonomy(user: dict = Depends(require_permission("understanding:read"))):
    return load_skill_aliases_taxonomy()


@router.get("/taxonomy/job-titles")
def get_job_titles_taxonomy(user: dict = Depends(require_permission("understanding:read"))):
    return load_job_titles_taxonomy()


@router.get("/taxonomy/job-title-aliases")
def get_title_aliases_taxonomy(user: dict = Depends(require_permission("understanding:read"))):
    return load_title_aliases_taxonomy()


@router.get("/taxonomy/snapshot")
def get_taxonomy_snapshot(user: dict = Depends(require_permission("understanding:read"))):
    return build_taxonomy_snapshot(validation_status="passed")


@router.post("/taxonomy/normalize")
def normalize_taxonomy_terms(
    request: TaxonomyNormalizeRequest,
    user: dict = Depends(require_permission("understanding:parse")),
):
    return {
        "result_version": "hermes_taxonomy_normalization_result_v1",
        "normalized_skills": [
            normalize_skill(skill)
            for skill in request.skills
        ],
        "normalized_job_titles": [
            normalize_job_title(title)
            for title in request.job_titles
        ],
    }


@router.post("/taxonomy/extract-signals")
def extract_taxonomy_signal_terms(
    request: TaxonomySignalExtractionRequest,
    user: dict = Depends(require_permission("understanding:parse")),
):
    return extract_taxonomy_signals(request.text)


@router.post("/taxonomy/suggestions")
def create_taxonomy_suggestions(
    request: TaxonomySuggestionRequest,
    user: dict = Depends(require_permission("understanding:parse")),
):
    return build_taxonomy_suggestions(
        skills=request.skills,
        job_titles=request.job_titles,
        source_context=request.source_context,
    )
