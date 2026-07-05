from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, UploadFile

from app.understanding.extractors.local_file import extract_local_file
from app.understanding.models import DocumentKind, RawDocument, UnderstandingResult
from app.understanding.service import build_understanding_result, understand_document
from app.understanding.taxonomy.loader import load_skills_taxonomy

router = APIRouter(prefix="/understanding", tags=["Understanding"])


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
