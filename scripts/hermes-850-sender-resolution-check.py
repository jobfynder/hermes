from app.email_parsing.sender_resolver import looks_forwarded, resolve_original_sender
from app.providers.email.service import normalize_email_payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


FORWARDED_NVOIDS_BODY = '''---------- Forwarded message ---------
From: Chandan Kumar <chandan.kumar@scalable-systems.com>
Date: Mon, Aug 24, 2026 at 9:36 AM
Subject: CITRIX NETWORK ADMINISTRATOR - Burlington, MA
To: nvoids@benchteq.com

Hi team,

We have an urgent requirement for a Citrix Network Administrator in
Burlington, MA (100% Onsite). Please share profiles.

Thanks,
Chandan
'''


def test_forwarded_nvoids_resolves_to_embedded_sender() -> None:
    require(
        looks_forwarded(FORWARDED_NVOIDS_BODY),
        'Forward marker was not detected',
    )

    result = resolve_original_sender(FORWARDED_NVOIDS_BODY)

    require(
        result['email'] == 'chandan.kumar@scalable-systems.com',
        f"Expected embedded recruiter email, got {result['email']!r}",
    )
    require(
        result['extraction_method'] == 'forwarded_header',
        'Expected forwarded_header extraction method',
    )
    require(
        result['confidence'] >= 0.9,
        'Forwarded header resolution should be high confidence',
    )


def test_forwarded_nvoids_infra_address_excluded() -> None:
    body = '''---------- Forwarded message ---------
From: nvoids <nvoids@benchteq.com>
Subject: fwd

Body text with no other contact.
'''
    result = resolve_original_sender(body)

    require(
        result['email'] is None,
        'nvoids forwarding address must never be returned as the resolved sender',
    )
    require(
        result['confidence'] == 0.0,
        'Unresolved sender must report zero confidence, not a guess',
    )


def test_reply_to_fallback() -> None:
    body = '''---------- Forwarded message ---------
Subject: no From line here
'''
    result = resolve_original_sender(body, reply_to_email='sam.recruiter@staffingco.com')

    require(
        result['email'] == 'sam.recruiter@staffingco.com',
        'Expected reply_to fallback to resolve the sender',
    )
    require(
        result['extraction_method'] == 'reply_to_header',
        'Expected reply_to_header extraction method',
    )


def test_body_contact_fallback() -> None:
    body = '''---------- Forwarded message ---------
Subject: no From, no reply-to

Interested candidates contact jane.doe@vendorcorp.com directly.
'''
    result = resolve_original_sender(body)

    require(
        result['email'] == 'jane.doe@vendorcorp.com',
        'Expected body-contact fallback to resolve the sender',
    )
    require(
        result['extraction_method'] == 'body_contact',
        'Expected body_contact extraction method',
    )


def test_no_resolution_does_not_guess() -> None:
    body = '''---------- Forwarded message ---------
Subject: nothing resolvable here, no emails at all
'''
    result = resolve_original_sender(body)

    require(result['email'] is None, 'Must not guess a sender when nothing resolves')
    require(result['extraction_method'] is None, 'extraction_method must be null when unresolved')


def test_non_forwarded_mail_is_left_alone() -> None:
    payload = {
        'from': {'email': 'direct.sender@jobfynder.com', 'name': 'Direct Sender'},
        'to': ['requirements@jobfynder.com'],
        'subject': 'Direct requirement, not forwarded',
        'text': 'Java developer needed in Dallas, TX.',
    }
    normalized = normalize_email_payload(payload)

    require(
        normalized['metadata']['original_sender_candidate'] is None,
        'Direct-send mail must not run sender resolution at all (spec 4.1/4.2: '
        'only forwarded sources need it, and it stays null otherwise)',
    )


def test_forwarded_mail_populates_intake_metadata() -> None:
    payload = {
        'from': {'email': 'nvoids@benchteq.com', 'name': 'nvoids'},
        'to': ['requirements@jobfynder.com'],
        'subject': 'Fwd: CITRIX NETWORK ADMINISTRATOR',
        'text': FORWARDED_NVOIDS_BODY,
    }
    normalized = normalize_email_payload(payload)
    candidate = normalized['metadata']['original_sender_candidate']

    require(candidate is not None, 'Forwarded mail must populate original_sender_candidate')
    require(
        candidate['email'] == 'chandan.kumar@scalable-systems.com',
        'Intake normalization did not resolve the real recruiter from the forwarded body',
    )


if __name__ == '__main__':
    test_forwarded_nvoids_resolves_to_embedded_sender()
    test_forwarded_nvoids_infra_address_excluded()
    test_reply_to_fallback()
    test_body_contact_fallback()
    test_no_resolution_does_not_guess()
    test_non_forwarded_mail_is_left_alone()
    test_forwarded_mail_populates_intake_metadata()
    print('hermes-850-sender-resolution-check: all checks passed')
