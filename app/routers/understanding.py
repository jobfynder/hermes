from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.understanding.extractors.local_file import extract_local_file
from app.understanding.models import DocumentKind, RawDocument, UnderstandingResult
from app.understanding.service import build_understanding_result, understand_document
from app.understanding.taxonomy.loader import (
    load_canonical_skills_taxonomy,
    load_job_titles_taxonomy,
    load_skill_aliases_taxonomy,
    load_skills_taxonomy,
    load_title_aliases_taxonomy,
)
from app.understanding.taxonomy.normalizer import normalize_job_title, normalize_skill

router = APIRouter(prefix="/understanding", tags=["Understanding"])


class TaxonomyNormalizeRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)


@router.post("/parse-text", response_model=UnderstandingResult)
def parse_text(document: RawDocument) -> UnderstandingResult:
    return understand_document(document)


@router.post("/parse-file", response_model=UnderstandingResult)
async def parse_file(
    file: UploadFile = File(...),
    document_kind: DocumentKind = Form("unknown"),
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
def get_skills_taxonomy():
    return load_skills_taxonomy()


@router.get("/taxonomy/skills/canonical")
def get_canonical_skills_taxonomy():
    return load_canonical_skills_taxonomy()


@router.get("/taxonomy/skills/aliases")
def get_skill_aliases_taxonomy():
    return load_skill_aliases_taxonomy()


@router.get("/taxonomy/job-titles")
def get_job_titles_taxonomy():
    return load_job_titles_taxonomy()


@router.get("/taxonomy/job-title-aliases")
def get_title_aliases_taxonomy():
    return load_title_aliases_taxonomy()


@router.post("/taxonomy/normalize")
def normalize_taxonomy_terms(request: TaxonomyNormalizeRequest):
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
