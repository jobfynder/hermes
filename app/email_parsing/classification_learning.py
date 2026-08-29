"""Self-learning email classification: hotlist vs. job requirement.

classify_email_by_confidence() (app/email_parsing/parsers.py) already
does real, content-based classification, and is left completely alone
by this module -- a confident classification is never overridden here.
This module exists for the genuinely ambiguous remainder: when content
alone can't decide, does *this sender's own history* lean one way?

Every correction a reviewer makes (via POST /drafts/{id}/reclassify)
becomes a row in classification_feedback (app/runtime/db.py, keyed by
sender domain, not full email -- one staffing company's several
recruiters should teach each other). Only ever used as a tie-breaker
for ambiguous emails, and only once a domain has more than one
correction on record (MIN_CORRECTIONS_FOR_BIAS) -- a single reviewer
fixing one mislabeled email is not yet a pattern.
"""

from __future__ import annotations

from typing import Any, Literal

from app.runtime.db import cursor

DocumentKindForLearning = Literal["hotlist", "job_description"]

# A single correction could be a one-off mistake by the sender (e.g. they
# usually send job requirements but this one email actually was a
# hotlist) -- more than one in the same direction is what makes it a
# real per-sender pattern worth trusting over the generic classifier.
MIN_CORRECTIONS_FOR_BIAS = 2


def _extract_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain or None


def record_classification_correction(
    draft_id: str,
    sender_email: str | None,
    predicted_document_kind: str,
    corrected_document_kind: str,
    predicted_confidence: float,
) -> None:
    """Records a reviewer's document_kind correction. A no-op when the
    'correction' actually agrees with the original classification --
    that confirms the classifier was right, not a pattern to learn a
    bias from.
    """
    if predicted_document_kind == corrected_document_kind:
        return

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO classification_feedback (
                draft_id, sender_domain, sender_email, predicted_document_kind,
                corrected_document_kind, predicted_confidence
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                draft_id,
                _extract_domain(sender_email),
                sender_email,
                predicted_document_kind,
                corrected_document_kind,
                predicted_confidence,
            ),
        )


def get_domain_bias(sender_email: str | None) -> dict[str, Any] | None:
    """Returns {"favored_document_kind", "correction_count", "confidence"}
    if this sender's domain has a clear historical lean, else None.
    "confidence" here is a plain agreement ratio (how often corrections
    for this domain landed on the favored kind), not a calibrated
    probability -- it only ever breaks a genuine content-classification
    tie, so it doesn't need to be more precise than "which way, and how
    consistently."
    """
    domain = _extract_domain(sender_email)
    if not domain:
        return None

    with cursor() as cur:
        cur.execute(
            """
            SELECT corrected_document_kind, count(*) AS n
            FROM classification_feedback
            WHERE sender_domain = %s
            GROUP BY corrected_document_kind
            ORDER BY n DESC
            """,
            (domain,),
        )
        rows = cur.fetchall()

    if not rows:
        return None

    total = sum(row["n"] for row in rows)
    if total < MIN_CORRECTIONS_FOR_BIAS:
        return None

    top = rows[0]
    return {
        "favored_document_kind": top["corrected_document_kind"],
        "correction_count": total,
        "confidence": round(top["n"] / total, 2),
    }
