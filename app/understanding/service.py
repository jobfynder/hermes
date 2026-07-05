from app.understanding.extractors.plain_text import extract_plain_text
from app.understanding.models import RawDocument, UnderstandingResult
from app.understanding.quality.scoring import score_extraction_quality


def understand_document(document: RawDocument) -> UnderstandingResult:
    extracted = extract_plain_text(
        content=document.content,
        filename=document.filename,
        content_type=document.content_type,
    )
    quality = score_extraction_quality(extracted)

    return UnderstandingResult(
        document_kind=document.document_kind,
        extracted_text=extracted,
        quality=quality,
        structured_data={},
    )
