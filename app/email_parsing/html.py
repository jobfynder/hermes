"""Small deterministic HTML-to-text helpers for inbound email bodies."""
import html as html_lib
import re


_IGNORED_CONTENT = re.compile(
    r"<(?:head|script|style)\b[^>]*>.*?</(?:head|script|style)\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_BLOCK_TAG = re.compile(
    r"</?(?:address|article|aside|blockquote|br|div|footer|h[1-6]|header|hr|li|main|nav|ol|p|pre|section|table|tbody|td|tfoot|th|thead|tr|ul)\b[^>]*>",
    flags=re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(value: str) -> str:
    """Convert an email HTML body to readable plain text without an LLM."""
    text = _IGNORED_CONTENT.sub("", value or "")
    text = _BLOCK_TAG.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\r?\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
