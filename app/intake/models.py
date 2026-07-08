from typing import Literal

from pydantic import BaseModel, Field


AttachmentStatus = Literal["received", "validated", "stored", "rejected", "failed"]

ALLOWED_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
}

ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}

MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024


class AttachmentValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)


class AttachmentRecord(BaseModel):
    attachment_id: str
    filename: str
    content_type: str | None = None
    size_bytes: int
    checksum_sha256: str
    storage_ref: str
    status: AttachmentStatus
    errors: list[str] = Field(default_factory=list)


class FileIntakeResult(BaseModel):
    result_version: str = "hermes_file_intake_result_v1"
    channel: str = "generic_api"
    source_message_id: str
    document_kind: str = "unknown"
    intake_status: str
    draft_object_type: str | None = None
    requires_review: bool = False
    confidence: float = 0.0
    normalized_skills: list[str] = Field(default_factory=list)
    normalized_job_titles: list[str] = Field(default_factory=list)
    taxonomy_signals: dict = Field(default_factory=dict)
    attachment: AttachmentRecord
    extracted_text: dict
    understanding_result: dict
    errors: list[str] = Field(default_factory=list)
