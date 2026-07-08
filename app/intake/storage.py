from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.intake.models import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_FILE_EXTENSIONS,
    MAX_ATTACHMENT_SIZE_BYTES,
    AttachmentRecord,
    AttachmentValidationResult,
)


STORAGE_ROOT = Path("/tmp/hermes-intake-files")


def checksum_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def validate_attachment(
    filename: str,
    content: bytes,
    content_type: str | None,
) -> AttachmentValidationResult:
    errors: list[str] = []
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_FILE_EXTENSIONS:
        errors.append("unsupported_file_extension")

    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        errors.append("unsupported_content_type")

    if len(content) <= 0:
        errors.append("empty_file")

    if len(content) > MAX_ATTACHMENT_SIZE_BYTES:
        errors.append("file_too_large")

    return AttachmentValidationResult(
        is_valid=not errors,
        errors=errors,
    )


def store_attachment(
    filename: str,
    content: bytes,
    content_type: str | None,
) -> AttachmentRecord:
    validation = validate_attachment(
        filename=filename,
        content=content,
        content_type=content_type,
    )

    attachment_id = str(uuid4())
    checksum = checksum_bytes(content)

    if not validation.is_valid:
        return AttachmentRecord(
            attachment_id=attachment_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=checksum,
            storage_ref="",
            status="rejected",
            errors=validation.errors,
        )

    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    safe_path = STORAGE_ROOT / f"{attachment_id}{suffix}"
    safe_path.write_bytes(content)

    return AttachmentRecord(
        attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        checksum_sha256=checksum,
        storage_ref=str(safe_path),
        status="stored",
        errors=[],
    )
