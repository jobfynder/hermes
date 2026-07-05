from langdetect import DetectorFactory, LangDetectException, detect
import tiktoken

from app.understanding.models import ExtractedText, ParseQuality

DetectorFactory.seed = 0


def detect_text_language(text: str) -> str:
    clean_text = text.strip()

    if len(clean_text) < 20:
        return "unknown"

    try:
        return detect(clean_text)
    except LangDetectException:
        return "unknown"


def estimate_token_count(text: str) -> int:
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text or ""))


def score_extraction_quality(extracted: ExtractedText) -> ParseQuality:
    text = extracted.text.strip()
    reasons: list[str] = []

    char_count = len(text)
    word_count = len(text.split())
    token_count = estimate_token_count(text)
    language = detect_text_language(text)

    if char_count < 40:
        reasons.append("text_too_short")

    if word_count < 5:
        reasons.append("too_few_words")

    if not any(char.isalpha() for char in text):
        reasons.append("no_alpha_text")

    if language == "unknown":
        reasons.append("language_unknown")

    confidence = 0.9

    if reasons:
        confidence = 0.55

    if "text_too_short" in reasons or "no_alpha_text" in reasons:
        confidence = 0.35

    return ParseQuality(
        confidence=confidence,
        needs_fallback=confidence < 0.7,
        reasons=reasons,
        metrics={
            "char_count": char_count,
            "word_count": word_count,
            "token_count": token_count,
            "language": language,
        },
    )
