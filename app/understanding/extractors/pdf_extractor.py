from pathlib import Path

import pdfplumber

from app.understanding.models import ExtractedText


def extract_pdf(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    pages: list[str] = []

    with pdfplumber.open(str(file_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())

    return ExtractedText(
        text="\n\n".join(pages).strip(),
        source="pdfplumber",
        filename=file_path.name,
        content_type="application/pdf",
        metadata={"page_count": len(pages)},
    )
