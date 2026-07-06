from app.config import HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED, HERMES_LLM_FALLBACK_ENABLED
from app.understanding.compression.token_budget import compress_to_token_budget
from app.understanding.extractors.plain_text import extract_plain_text
from app.understanding.fallback_policy import decide_fallback
from app.understanding.models import DocumentKind, ExtractedText, RawDocument, UnderstandingResult
from app.understanding.parsers.basic import parse_basic_structured_data
from app.understanding.quality.scoring import score_extraction_quality
from app.understanding.quality.thresholds import apply_document_quality_threshold
from app.understanding.validation import validate_structured_output


DEFAULT_LLM_CONTEXT_TOKENS = 1200


def build_understanding_result(
    extracted: ExtractedText,
    document_kind: DocumentKind = "unknown",
) -> UnderstandingResult:
    quality = apply_document_quality_threshold(
        document_kind=document_kind,
        quality=score_extraction_quality(extracted),
    )
    compressed = compress_to_token_budget(
        extracted.text,
        max_tokens=DEFAULT_LLM_CONTEXT_TOKENS,
    )
    structured_data = parse_basic_structured_data(
        extracted=extracted,
        document_kind=document_kind,
    )
    validation = validate_structured_output(
        document_kind=document_kind,
        structured_data=structured_data,
        quality=quality,
    )
    fallback = decide_fallback(
        extracted=extracted,
        quality=quality,
        cloud_fallback_enabled=HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED,
        llm_fallback_enabled=HERMES_LLM_FALLBACK_ENABLED,
    )

    return UnderstandingResult(
        document_kind=document_kind,
        extracted_text=extracted,
        quality=quality,
        validation=validation.model_dump(),
        fallback=fallback.model_dump(),
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
