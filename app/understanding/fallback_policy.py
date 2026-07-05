from typing import Any, Literal

from pydantic import BaseModel, Field

from app.understanding.models import ExtractedText, ParseQuality


FallbackAction = Literal[
    "none",
    "local_retry",
    "cloud_extraction_candidate",
    "llm_structuring_candidate",
    "manual_review",
]


class FallbackDecision(BaseModel):
    action: FallbackAction = "none"
    should_call_cloud_extraction: bool = False
    should_call_llm: bool = False
    reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def decide_fallback(
    extracted: ExtractedText,
    quality: ParseQuality,
    cloud_fallback_enabled: bool = False,
    llm_fallback_enabled: bool = False,
) -> FallbackDecision:
    reasons: list[str] = list(quality.reasons)

    if not quality.needs_fallback:
        return FallbackDecision(
            action="none",
            reasons=[],
            metadata={
                "confidence": quality.confidence,
                "source": extracted.source,
            },
        )

    attempted_sources = extracted.metadata.get("attempted_sources", [])

    if extracted.source == "markitdown" and "pdfplumber" not in attempted_sources:
        return FallbackDecision(
            action="local_retry",
            reasons=reasons + ["try_specialized_local_extractor"],
            metadata={
                "confidence": quality.confidence,
                "source": extracted.source,
                "attempted_sources": attempted_sources,
            },
        )

    if cloud_fallback_enabled:
        return FallbackDecision(
            action="cloud_extraction_candidate",
            should_call_cloud_extraction=True,
            reasons=reasons + ["local_extraction_weak"],
            metadata={
                "confidence": quality.confidence,
                "source": extracted.source,
                "attempted_sources": attempted_sources,
            },
        )

    if llm_fallback_enabled and extracted.text.strip():
        return FallbackDecision(
            action="llm_structuring_candidate",
            should_call_llm=True,
            reasons=reasons + ["parser_confidence_low_but_text_available"],
            metadata={
                "confidence": quality.confidence,
                "source": extracted.source,
                "attempted_sources": attempted_sources,
            },
        )

    return FallbackDecision(
        action="manual_review",
        reasons=reasons + ["fallback_disabled_or_no_usable_text"],
        metadata={
            "confidence": quality.confidence,
            "source": extracted.source,
            "attempted_sources": attempted_sources,
        },
    )
