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
# Also reused by signature.py's sender-domain website fallback -- the
# same reasoning applies: a freemail domain isn't a company's website
# either.
FREEMAIL_DOMAINS = {
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

SHARED_RELAY_DOMAINS = {
    "jobfynder.com",
    "nvoids.com",
    "jobs.nvoids.com",
    "prohirespowerhouse.com",
    "groups.google.com",
    "googlegroups.com",
    "techmail001.email",
}


def _is_learnable_domain(sender_domain: str | None) -> bool:
    return bool(sender_domain) and sender_domain not in FREEMAIL_DOMAINS | SHARED_RELAY_DOMAINS


def _contact_domain(contact: dict) -> str | None:
    email = contact.get("email") or {}
    value = email.get("value") if isinstance(email, dict) else None
    if not value or "@" not in value:
        return None
    domain = value.rsplit("@", 1)[-1].strip().lower()
    return domain if _is_learnable_domain(domain) else None


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
    # A relay transport domain is not the recruiter's company. Prefer the
    # corporate address extracted from the signature; use the transport
    # sender only when it is itself a real corporate domain.
    learned_domain = _contact_domain(contact) or (
        sender_domain if _is_learnable_domain(sender_domain) else None
    )
    if not learned_domain:
        return []

    with cursor() as cur:
        cur.execute(
            "SELECT field, corrected_value FROM signature_corrections WHERE sender_domain = %s",
            (learned_domain,),
        )
        rows = cur.fetchall()

        # Company Master is a deterministic consensus built from source-backed
        # signature observations. Two independent observations are required
        # before it may fill a missing company; a single parse can never teach
        # itself and immediately become accepted evidence.
        company_name = None
        existing_company = contact.get("company_name")
        existing_company_value = (
            existing_company.get("value") if isinstance(existing_company, dict) else existing_company
        )
        if not existing_company_value:
            cur.execute(
                "SELECT c.canonical_name FROM hermes_companies c "
                "WHERE c.identity_domain=%s AND "
                "(SELECT count(*) FROM company_observations o WHERE o.company_id=c.company_id) >= 2",
                (learned_domain,),
            )
            company = cur.fetchone()
            company_name = company["canonical_name"] if company else None

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
            "source": learned_domain,
        }
        applied.append(field)

    if company_name:
        contact["company_name"] = {
            "value": company_name,
            "raw": None,
            "confidence": 0.85,
            "method": "learned_from_company_master",
            "source": learned_domain,
        }
        applied.append("company_name")

    return applied
