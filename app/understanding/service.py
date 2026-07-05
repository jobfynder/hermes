from app.understanding.models import ExtractedText, ParseQuality, RawDocument, UnderstandingResult


def extract_plain_text(document: RawDocument) -> ExtractedText:
    return ExtractedText(
        text=document.content.strip(),
        source="plain_text",
        filename=document.filename,
        content_type=document.content_type,
    )


def score_extraction_quality(extracted: ExtractedText) -> ParseQuality:
    text = extracted.text.strip()
    reasons: list[str] = []

    if len(text) < 40:
        reasons.append("text_too_short")

    if not any(char.isalpha() for char in text):
        reasons.append("no_alpha_text")

    confidence = 0.9
    if reasons:
        confidence = 0.45

    return ParseQuality(
        confidence=confidence,
        needs_fallback=confidence < 0.7,
        reasons=reasons,
    )


def understand_document(document: RawDocument) -> UnderstandingResult:
    extracted = extract_plain_text(document)
    quality = score_extraction_quality(extracted)

    return UnderstandingResult(
        document_kind=document.document_kind,
        extracted_text=extracted,
        quality=quality,
        structured_data={},
    )
