from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["Draft Review"])
_REVIEW_HTML = Path(__file__).resolve().parent.parent / "static" / "draft-review.html"


@router.get("/review", response_class=HTMLResponse, include_in_schema=False)
def draft_review() -> HTMLResponse:
    """Serve the read-only draft review client.

    Draft data remains protected by the existing /drafts RBAC dependency. The
    page itself contains no data or credentials; the reviewer supplies their
    API token directly to the browser client.
    """
    return HTMLResponse(_REVIEW_HTML.read_text(encoding="utf-8"))
