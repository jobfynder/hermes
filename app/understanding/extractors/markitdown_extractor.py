from pathlib import Path

from markitdown import MarkItDown

from app.understanding.models import ExtractedText


def extract_markitdown(path: str | Path) -> ExtractedText:
    file_path = Path(path)
    converter = MarkItDown()
    result = converter.convert(str(file_path))

    return ExtractedText(
        text=(result.text_content or "").strip(),
        source="markitdown",
        filename=file_path.name,
        content_type=None,
        metadata={},
    )
