from pathlib import Path

from app.intake.models import FileIntakeResult
from app.intake.storage import store_attachment
from app.understanding.extractors.local_file import extract_local_file
from app.understanding.models import DocumentKind
from app.understanding.service import build_understanding_result


def process_file_intake(
    filename: str,
    content: bytes,
    content_type: str | None,
    document_kind: DocumentKind = "unknown",
) -> FileIntakeResult:
    attachment = store_attachment(
        filename=filename,
        content=content,
        content_type=content_type,
    )

    if attachment.status != "stored":
        return FileIntakeResult(
            attachment=attachment,
            extracted_text={},
            understanding_result={
                "status": "failed",
                "errors": attachment.errors,
            },
        )

    extracted = extract_local_file(Path(attachment.storage_ref))
    extracted.filename = filename
    extracted.content_type = content_type

    understanding = build_understanding_result(
        extracted=extracted,
        document_kind=document_kind,
    )

    return FileIntakeResult(
        attachment=attachment,
        extracted_text=extracted.model_dump(),
        understanding_result=understanding.model_dump(),
    )
