from pathlib import Path

from docx import Document

from app.understanding.models import ExtractedText


def extract_docx(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    document = Document(str(file_path))

    paragraphs = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text and paragraph.text.strip()
    ]

    return ExtractedText(
        text="\n".join(paragraphs).strip(),
        source="python_docx",
        filename=file_path.name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata={"paragraph_count": len(paragraphs)},
    )
