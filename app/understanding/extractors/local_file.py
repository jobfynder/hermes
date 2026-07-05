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
        metadata={"attempted_sources": ["plain_text"]},
    )


def add_attempted_sources(
    extracted: ExtractedText,
    attempted_sources: list[str],
) -> ExtractedText:
    extracted.metadata = {
        **extracted.metadata,
        "attempted_sources": attempted_sources,
    }
    return extracted


def extract_local_file(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    suffix = file_path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return extract_text_file(file_path)

    attempted_sources = ["markitdown"]

    try:
        extracted = extract_markitdown(file_path)
        if extracted.text:
            return add_attempted_sources(extracted, attempted_sources)
    except Exception:
        pass

    if suffix == ".pdf":
        attempted_sources.append("pdfplumber")
        extracted = extract_pdf(file_path)
        return add_attempted_sources(extracted, attempted_sources)

    if suffix == ".docx":
        attempted_sources.append("python_docx")
        extracted = extract_docx(file_path)
        return add_attempted_sources(extracted, attempted_sources)

    return ExtractedText(
        text="",
        source="unknown",
        filename=file_path.name,
        content_type=None,
        metadata={"attempted_sources": attempted_sources},
    )
