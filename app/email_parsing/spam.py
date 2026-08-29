"""Spam/junk heuristic (HERMES-900). Flag-only by design (see
DraftStatus.spam in app/drafts/models.py) -- nothing here ever deletes or
silently discards a message; classify_channel_intake_spam() only decides
whether a draft gets created with status='spam' instead of the usual
draft/needs_review, so a human always makes the final call in the
frontend. Blocking a known-bad sender entirely is a separate, earlier
step -- see app/email_parsing/blocklist.py -- for senders you've already
decided about; this module is for senders you haven't.

Deterministic and conservative on purpose: a false positive here is
recoverable (a human just reclassifies it back), but flagging too
aggressively trains reviewers to stop trusting the "Spam" tag, which
defeats the point at 5,000 emails/day.
"""

from __future__ import annotations

import re

# A real job posting or hotlist -- even a badly-formatted one -- almost
# always mentions at least one of these. Their absence is not proof of
# spam by itself, but combined with marketing-footer language it is a
# strong signal this is bulk mail that was never about a role at all.
_JOB_CONTENT_MARKERS_RE = re.compile(
    r"\b(?:required skills?|job title|position|location|hotlist|consultant|"
    r"rate|contract|visa|resume|experience|responsibilities|qualifications|"
    r"client|w2|c2c|1099)\b",
    flags=re.IGNORECASE,
)

_MARKETING_MARKERS = (
    "unsubscribe",
    "view in browser",
    "you are receiving this email because",
    "click here to",
    "limited time offer",
    "act now",
    "% off",
    "manage your subscription",
    "this is a promotional email",
)

MIN_CONTENT_LENGTH = 25


def classify_spam(
    text: str,
    document_kind: str,
    confidence: float,
) -> list[str]:
    """Returns a list of reasons this looks like spam/junk, empty if it
    doesn't. Call sites treat a non-empty list as "flag it", never as
    "discard it" -- see the module docstring.
    """
    reasons: list[str] = []
    stripped = (text or "").strip()

    if len(stripped) < MIN_CONTENT_LENGTH:
        reasons.append("empty_or_near_empty_content")
        return reasons

    if document_kind in {"unknown", "plain_message"} and confidence < 0.35:
        reasons.append("no_hotlist_or_requirement_signal")

    lowered = stripped.lower()
    marketing_hits = sum(1 for marker in _MARKETING_MARKERS if marker in lowered)
    has_job_content = bool(_JOB_CONTENT_MARKERS_RE.search(lowered))

    # Two independent marketing markers is deliberately the bar, not one --
    # a single "unsubscribe" footer is completely normal on a legitimate
    # job-board relay (jobs.nvoids.com and similar all carry one). It's the
    # *combination* of several marketing-email tells with *zero* job
    # content that is the actual signal.
    if marketing_hits >= 2 and not has_job_content:
        reasons.append("marketing_footer_markers_without_job_content")

    return reasons
