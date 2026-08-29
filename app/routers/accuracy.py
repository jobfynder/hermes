from fastapi import APIRouter, Depends

from app.drafts.accuracy import compute_accuracy_summary
from app.security.rbac import require_permission

router = APIRouter(prefix="/accuracy", tags=["Accuracy"])


@router.get("/summary")
def get_accuracy_summary(
    days: int = 30,
    _user: dict = Depends(require_permission("drafts:read")),
) -> dict:
    """Per-field fill-rate and precision for both draft types, computed
    from field_provenance (see app/drafts/accuracy.py for the full
    methodology) -- not a hand-labeled test corpus, but the real,
    continuously-growing signal produced as a side effect of reviewers
    and recruiters doing their normal jobs.
    """
    return compute_accuracy_summary(days=days)
