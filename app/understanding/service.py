from app.config import HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED, HERMES_LLM_FALLBACK_ENABLED
from app.understanding.compression.token_budget import compress_to_token_budget
from app.understanding.extractors.plain_text import extract_plain_text
from app.understanding.fallback_policy import decide_fallback
from app.understanding.llm_fallback import apply_llm_fallback
from app.understanding.models import DocumentKind, ExtractedText, RawDocument, UnderstandingResult
from app.understanding.parsers.basic import parse_basic_structured_data
from app.understanding.quality.scoring import score_extraction_quality
from app.understanding.quality.thresholds import apply_document_quality_threshold
from app.understanding.taxonomy.signals import extract_taxonomy_signals
from app.understanding.validation import validate_structured_output
from app.runtime.cache import build_cache_key, cache_get, cache_set


DEFAULT_LLM_CONTEXT_TOKENS = 1200
PARSER_VERSION = "basic_local_parser_v1"
PARSE_CACHE_TTL_SECONDS = 86400
CACHEABLE_DOCUMENT_KINDS = {"resume", "job_description"}


def build_understanding_result(
    extracted: ExtractedText,
    document_kind: DocumentKind = "unknown",
    skip_llm_fallback: bool = False,
) -> UnderstandingResult:
    cache_key = None

    if document_kind in CACHEABLE_DOCUMENT_KINDS:
        cache_key = build_cache_key(
            "parse", extracted.text, document_kind, PARSER_VERSION, skip_llm_fallback
        )
        cached = cache_get(cache_key)

        if cached is not None:
            return UnderstandingResult(**cached)

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

    taxonomy_signals = extract_taxonomy_signals(extracted.text)
    structured_data["taxonomy_signals"] = taxonomy_signals
    structured_data["normalized_skills"] = [
        signal["normalized"]
        for signal in taxonomy_signals.get("skills", [])
    ]
    structured_data["normalized_job_titles"] = [
        signal["normalized"]
        for signal in taxonomy_signals.get("job_titles", [])
    ]
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
    fallback_dump = fallback.model_dump()

    if fallback.should_call_llm and not skip_llm_fallback:
        llm_outcome = apply_llm_fallback(
            document_kind=document_kind,
            extracted=extracted,
        )
        fallback_dump["llm_fallback"] = llm_outcome

        if llm_outcome.get("used"):
            structured_data["llm_fallback_extracted"] = llm_outcome["extracted"]

    result = UnderstandingResult(
        document_kind=document_kind,
        extracted_text=extracted,
        quality=quality,
        validation=validation.model_dump(),
        fallback=fallback_dump,
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

    if cache_key:
        cache_set(cache_key, result.model_dump(), PARSE_CACHE_TTL_SECONDS)

    return result


def understand_document(
    document: RawDocument,
    skip_llm_fallback: bool = False,
) -> UnderstandingResult:
    extracted = extract_plain_text(
        content=document.content,
        filename=document.filename,
        content_type=document.content_type,
    )

    return build_understanding_result(
        extracted=extracted,
        document_kind=document.document_kind,
        skip_llm_fallback=skip_llm_fallback,
    )
