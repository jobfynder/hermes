from app.understanding.models import ExtractedText


def extract_plain_text(
    content: str,
    filename: str | None = None,
    content_type: str | None = None,
) -> ExtractedText:
    return ExtractedText(
        text=content.strip(),
        source="plain_text",
        filename=filename,
        content_type=content_type,
        metadata={},
    )
