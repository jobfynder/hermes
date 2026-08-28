import re
from typing import Any


PARSER_METADATA = {
    'name': 'hermes_email_sender_resolver',
    'version': 'hermes_email_sender_resolver_v1',
    'uses_llm': False,
}


# Addresses that are infrastructure (forwarding services, no-reply senders)
# rather than a recruiter's real contact -- never returned as the resolved
# sender even if they appear in the body or headers.
_INFRA_ADDRESS_MARKERS = ('noreply', 'no-reply', 'donotreply', 'do-not-reply', 'nvoids')

_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# Matches the standard forwarded-message block produced by Gmail/Outlook, e.g.:
#   ---------- Forwarded message ---------
#   From: Chandan Kumar <chandan.kumar@scalable-systems.com>
#   Date: Mon, Aug 24, 2026 at 9:36 AM
#   Subject: ...
_FORWARD_MARKER_RE = re.compile(
    r'-{2,}\s*(?:forwarded message|original message)\s*-{2,}',
    re.IGNORECASE,
)
_FORWARD_FROM_RE = re.compile(
    r'^\s*from\s*:\s*(?:(?P<name>[^<\r\n]+?)\s*)?<?(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)>?\s*$',
    re.IGNORECASE | re.MULTILINE,
)

# Bounded search window after a forward marker -- the forwarded header block
# is always the first few lines, not the entire quoted thread below it.
_FORWARD_HEADER_WINDOW_CHARS = 2000


def _is_infra_address(email: str) -> bool:
    lowered = email.lower()
    return any(marker in lowered for marker in _INFRA_ADDRESS_MARKERS)


def _find_forwarded_header_sender(body: str) -> tuple[str | None, str | None]:
    marker = _FORWARD_MARKER_RE.search(body)

    if not marker:
        return None, None

    window = body[marker.end():marker.end() + _FORWARD_HEADER_WINDOW_CHARS]
    match = _FORWARD_FROM_RE.search(window)

    if not match:
        return None, None

    email = match.group('email')

    if _is_infra_address(email):
        return None, None

    name = (match.group('name') or '').strip().strip('"') or None
    return email, name


def _find_body_contact_email(body: str) -> str | None:
    for candidate in _EMAIL_RE.findall(body):
        if not _is_infra_address(candidate):
            return candidate

    return None


def resolve_original_sender(
    text: str,
    reply_to_email: str | None = None,
) -> dict[str, Any]:
    '''Recover the real sender of a forwarded email, deterministically.

    Some inbound sources (e.g. a recruiter mailing list that forwards
    postings rather than sending or CC'ing them directly) put the outer
    envelope From on a forwarding address, not the recruiter who actually
    wrote the message. Any downstream verify-and-claim flow that emails the
    "sender" back needs the real recruiter, not the forwarder -- guessing
    wrong here means mailing a stranger or a dead relay address, so an
    unresolved case returns a null candidate rather than a low-confidence
    guess.

    Resolution order (highest confidence first):
      1. A forwarded-message header block embedded in the body.
      2. The Reply-To address, if the source preserved one.
      3. A contact email found anywhere else in the body text.
      4. None resolve -- return a null candidate. Callers must not guess.
    '''

    body = text or ''

    email, name = _find_forwarded_header_sender(body)
    if email:
        return {
            'email': email,
            'name': name,
            'extraction_method': 'forwarded_header',
            'confidence': 0.95,
        }

    if reply_to_email and not _is_infra_address(reply_to_email):
        return {
            'email': reply_to_email,
            'name': None,
            'extraction_method': 'reply_to_header',
            'confidence': 0.75,
        }

    body_email = _find_body_contact_email(body)
    if body_email:
        return {
            'email': body_email,
            'name': None,
            'extraction_method': 'body_contact',
            'confidence': 0.55,
        }

    return {
        'email': None,
        'name': None,
        'extraction_method': None,
        'confidence': 0.0,
    }


def looks_forwarded(text: str) -> bool:
    '''Cheap pre-check so callers only invoke resolution on likely-forwarded
    mail instead of scanning every message body for a forward marker.'''

    return bool(_FORWARD_MARKER_RE.search(text or ''))


def forwarded_marker_span(text: str) -> tuple[int, int] | None:
    '''Character span of the "---- Forwarded message ----" / "---- Original
    message ----" marker, or None. Public so other modules that need to
    bound "current message only" text (e.g. app/email_parsing/signature.py,
    which must not scan quoted/forwarded history for a signature) can reuse
    the same marker definition instead of duplicating the regex.'''

    match = _FORWARD_MARKER_RE.search(text or '')
    return match.span() if match else None


def find_body_contact_email(text: str) -> str | None:
    """Public wrapper so other modules (e.g. app/claim/service.py) can
    reuse the same non-infra email search without reaching into a private
    function."""
    return _find_body_contact_email(text or '')
