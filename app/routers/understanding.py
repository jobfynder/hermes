from fastapi import APIRouter

from app.understanding.models import RawDocument, UnderstandingResult
from app.understanding.service import understand_document

router = APIRouter(prefix="/understanding", tags=["Understanding"])


@router.post("/parse-text", response_model=UnderstandingResult)
def parse_text(document: RawDocument) -> UnderstandingResult:
    return understand_document(document)
