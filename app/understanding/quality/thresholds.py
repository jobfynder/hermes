from app.understanding.models import DocumentKind, ParseQuality


DEFAULT_QUALITY_THRESHOLDS: dict[DocumentKind, float] = {
    "resume": 0.70,
    "job_description": 0.70,
    "message": 0.60,
    "unknown": 0.70,
}


def get_quality_threshold(document_kind: DocumentKind) -> float:
    return DEFAULT_QUALITY_THRESHOLDS.get(document_kind, 0.70)


def apply_document_quality_threshold(
    document_kind: DocumentKind,
    quality: ParseQuality,
) -> ParseQuality:
    threshold = get_quality_threshold(document_kind)
    needs_fallback = quality.confidence < threshold

    metrics = {
        **quality.metrics,
        "quality_threshold": threshold,
        "threshold_document_kind": document_kind,
    }

    return ParseQuality(
        confidence=quality.confidence,
        needs_fallback=needs_fallback,
        reasons=quality.reasons,
        metrics=metrics,
    )
