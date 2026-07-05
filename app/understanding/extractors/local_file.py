from pathlib import Path

from app.understanding.extractors.docx_extractor import extract_docx
from app.understanding.extractors.markitdown_extractor import extract_markitdown
from app.understanding.extractors.pdf_extractor import extract_pdf
from app.understanding.models import ExtractedText


def extract_text_file(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="ignore")

    return ExtractedText(
        text=text.strip(),
        source="plain_text",
        filename=file_path.name,
        content_type="text/plain",
        metadata={},
    )


def extract_local_file(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    suffix = file_path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return extract_text_file(file_path)

    if suffix == ".pdf":
        extracted = extract_pdf(file_path)
        if extracted.text:
            return extracted

    if suffix == ".docx":
        extracted = extract_docx(file_path)
        if extracted.text:
            return extracted

    return extract_markitdown(file_path)
