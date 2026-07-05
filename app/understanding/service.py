from app.understanding.compression.token_budget import compress_to_token_budget
from app.understanding.extractors.plain_text import extract_plain_text
from app.understanding.models import DocumentKind, ExtractedText, RawDocument, UnderstandingResult
from app.understanding.parsers.basic import parse_basic_structured_data
from app.understanding.quality.scoring import score_extraction_quality


DEFAULT_LLM_CONTEXT_TOKENS = 1200


def build_understanding_result(
    extracted: ExtractedText,
    document_kind: DocumentKind = "unknown",
) -> UnderstandingResult:
    quality = score_extraction_quality(extracted)
    compressed = compress_to_token_budget(
        extracted.text,
        max_tokens=DEFAULT_LLM_CONTEXT_TOKENS,
    )
    structured_data = parse_basic_structured_data(
        extracted=extracted,
        document_kind=document_kind,
    )

    return UnderstandingResult(
        document_kind=document_kind,
        extracted_text=extracted,
        quality=quality,
        llm_context={
            "text": compressed.text,
            "original_token_count": compressed.original_token_count,
            "compressed_token_count": compressed.compressed_token_count,
            "max_tokens": compressed.max_tokens,
            "compression_applied": compressed.compression_applied,
            "strategy": compressed.strategy,
        },
        structured_data=structured_data,
    )


def understand_document(document: RawDocument) -> UnderstandingResult:
    extracted = extract_plain_text(
        content=document.content,
        filename=document.filename,
        content_type=document.content_type,
    )

    return build_understanding_result(
        extracted=extracted,
        document_kind=document.document_kind,
    )
