from typing import Any, Literal

from pydantic import BaseModel, Field


DocumentKind = Literal["resume", "job_description", "message", "unknown"]
ExtractionSource = Literal["plain_text", "markitdown", "pdfplumber", "python_docx", "unstructured", "unknown"]


class RawDocument(BaseModel):
    content: str = Field(..., min_length=1)
    filename: str | None = None
    content_type: str | None = None
    document_kind: DocumentKind = "unknown"


class ExtractedText(BaseModel):
    text: str
    source: ExtractionSource = "plain_text"
    filename: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParseQuality(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_fallback: bool = False
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class UnderstandingResult(BaseModel):
    document_kind: DocumentKind
    extracted_text: ExtractedText
    quality: ParseQuality
    llm_context: dict[str, Any] = Field(default_factory=dict)
    structured_data: dict[str, Any] = Field(default_factory=dict)
