"""Per-sender-domain pattern learning for signature fields.

parse_email_signature() (app/email_parsing/signature.py) is deterministic
and left completely alone here -- a field it did extract is never
overridden. This module exists for the fields it missed: when a reviewer
corrects a signature field (a company name that never parses right for one
staffing vendor's format, say), that correction is remembered per sender
domain in signature_corrections (app/runtime/db.py). The next email from
the same domain gets that specific gap filled in automatically instead of
a reviewer fixing the same field on every single email from that sender.

Deliberately gap-filling only, never overwriting: a domain where the
signature genuinely varies per sender (a staffing company with many
recruiters, each with their own title) never gets one recruiter's
corrected value silently stamped onto another's email.

A sender domain only means "one company" for a real corporate domain.
Shared public mail providers (gmail.com, yahoo.com, ...) are used by
thousands of unrelated senders -- one recruiter's corrected name/company
learned there and applied to every other gmail.com sender is not a
pattern, it's a false identity stamped onto strangers. Confirmed in
production: a single correction for one gmail.com sender ("Sekhar U,
Sr.IT Technical Recruiter, Tekwings LLC") got applied to 700+ unrelated
drafts from other recruiters who also happen to mail from gmail.com,
because a job-board relay (jobs.nvoids.com) sends on behalf of many
different people through their own personal gmail addresses. Freemail
domains are excluded from both recording and applying learned patterns.
"""

from __future__ import annotations

from app.runtime.db import cursor

# Not exhaustive -- just common enough that a "correction" learned here
# is guaranteed to belong to one specific person, not their employer.
# Extend this list rather than ever learning patterns for one of these.
_FREEMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "aol.com",
    "icloud.com",
    "me.com",
    "protonmail.com",
    "gmx.com",
    "ymail.com",
    "rediffmail.com",
}


def _is_learnable_domain(sender_domain: str | None) -> bool:
    return bool(sender_domain) and sender_domain not in _FREEMAIL_DOMAINS


def record_signature_correction(sender_domain: str, field: str, value: str) -> None:
    if not _is_learnable_domain(sender_domain) or not field or not value:
        return

    with cursor() as cur:
        cur.execute(
            "INSERT INTO signature_corrections (sender_domain, field, corrected_value, updated_at) "
            "VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (sender_domain, field) "
            "DO UPDATE SET corrected_value = EXCLUDED.corrected_value, updated_at = now()",
            (sender_domain, field, value),
        )


def apply_learned_signature_patterns(contact: dict, sender_domain: str | None) -> list[str]:
    """Fills in fields the parser missed on this email using values a
    reviewer previously confirmed for the same sender domain. Mutates
    `contact` in place and returns the list of fields it filled in.
    """
    if not _is_learnable_domain(sender_domain):
        return []

    with cursor() as cur:
        cur.execute(
            "SELECT field, corrected_value FROM signature_corrections WHERE sender_domain = %s",
            (sender_domain,),
        )
        rows = cur.fetchall()

    applied: list[str] = []

    for row in rows:
        field = row["field"]
        existing = contact.get(field)
        if existing and existing.get("value"):
            continue

        contact[field] = {
            "value": row["corrected_value"],
            "raw": None,
            "confidence": 0.75,
            "method": "learned_from_domain_pattern",
            "source": sender_domain,
        }
        applied.append(field)

    return applied
