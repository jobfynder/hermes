#!/usr/bin/env python3
"""Checks for app/email_parsing/signature.py -- this parser had no
regression coverage at all before HERMES-850's extraction-quality pass,
despite being one of the more intricate heuristic modules in the codebase
(quoted/forwarded-history boundary detection, structural signature-span
detection, name/title/company/LinkedIn extraction).
"""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.email_parsing.signature import parse_email_signature


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def contact_values(sig: dict) -> dict:
    return {
        k: (v.get("value") if isinstance(v, dict) else v)
        for k, v in sig.get("contact", {}).items()
    }


def test_normal_signoff_signature() -> None:
    text = """Hi team,

We have a new requirement, please see attached.

Regards,
John Smith
Senior Technical Recruiter
Acme Staffing Solutions
john.smith@acmestaffing.com
linkedin.com/in/johnsmith
(555) 123-4567
"""

    sig = parse_email_signature(text=text, sender_email="john.smith@acmestaffing.com")
    contact = contact_values(sig)

    require(sig["detected"] is True, "A normal signed-off email must detect a signature")
    require(contact.get("full_name") == "John Smith", f"Wrong name: {contact}")
    require(contact.get("job_title") == "Senior Technical Recruiter", f"Wrong title: {contact}")
    require(contact.get("company_name") == "Acme Staffing Solutions", f"Wrong company: {contact}")
    require(
        contact.get("linkedin_url") == "https://linkedin.com/in/johnsmith",
        f"Wrong LinkedIn URL: {contact}",
    )


def test_pure_forward_recovers_email_and_website() -> None:
    # Regression fixture for the HERMES-850 "recruiter signature not
    # parsed" incident: a job-board email that is nothing but a single
    # forward -- the whole body sits past signature.py's own quoted-
    # history boundary, which used to mean parse_email_signature() found
    # nothing at all for every email of this (very common) shape.
    text = """Subject: FW: Senior Java Developer - Contract - NYC

From: harry@itecsus.com <harry@itecsus.com>
Sent: Saturday, August 29, 2026 6:38 AM
To: Jobs Nvoids <jobs@nvoids.com>
Subject: Senior Java Developer - Contract - NYC

You received this email from harry@itecsus.com via https://jobs.nvoids.com

We have a requirement for a Senior Java Developer.

Required skills: Java, Spring Boot, AWS

harry@itecsus.com
View this job online here
"""

    sig = parse_email_signature(text=text, sender_email="jobs@jobfynder.com")

    require(
        sig["quoted_signature_ignored"] is False,
        "A message that IS a single forward, with nothing above it, has "
        "no fresh content to protect -- it must not be waved off as "
        "quoted history",
    )
    require(sig["detected"] is True, f"Must detect something in a pure forward: {sig}")
    contact = contact_values(sig)
    require(
        contact.get("email") == "harry@itecsus.com",
        f"Must recover the sender's own email from within the forward: {contact}",
    )


def test_forwarded_header_block_itself_is_not_mistaken_for_signature() -> None:
    # The forwarded header block's own repeated "Subject: ..." line must
    # never be picked up as if it were the sender's job title -- a real
    # regression hit while building the pure-forward fix above.
    text = """Subject: FW: AWS Connect Solutions Engineer - Oncor

From: harry@itecsus.com <harry@itecsus.com>
Sent: Saturday, August 29, 2026 6:38 AM
To: Jobs Nvoids <jobs@nvoids.com>
Subject: AWS Connect Solutions Engineer - Oncor

You received this email from harry@itecsus.com via https://jobs.nvoids.com

Required skills: Amazon Connect, AWS Lambda
"""

    sig = parse_email_signature(text=text, sender_email="jobs@jobfynder.com")
    contact = contact_values(sig)

    require(
        contact.get("job_title") != "AWS Connect Solutions Engineer - Oncor",
        f"The header block's own Subject: line must not be read as a job title: {contact}",
    )


def test_ner_fallback_recovers_fragmented_name() -> None:
    # Regression fixture for the specific limitation flagged after the
    # pure-forward fix above shipped: a real vendor's forwarded postings
    # render the sender's own name/company as one bare token per line
    # ("From: / / Harry, / / ITECSUS / / harry@itecsus.com") with no
    # title keyword, no recognized company suffix, and no multi-word
    # name on a single line -- nothing the regex-only pass can anchor
    # on. The NER fallback (en_core_web_sm, gated to only the
    # is_pure_forward case -- see parse_email_signature) should recover
    # at least the person's name from this.
    text = """Subject: FW: AWS Connect Solutions Engineer with IVR Exp : Houston, TX

From: harry@itecsus.com <harry@itecsus.com>
Sent: Saturday, August 29, 2026 6:38 AM
To: Jobs Nvoids <jobs@nvoids.com>
Subject: AWS Connect Solutions Engineer with IVR Exp : Houston, TX

You received this email from harry@itecsus.com via https://jobs.nvoids.com
Please check the email id in the signature to reply to the correct email id.

From:

Harry,

ITECSUS

harry@itecsus.com

Reply to: harry@itecsus.com
"""

    sig = parse_email_signature(text=text, sender_email="jobs@jobfynder.com")
    contact = contact_values(sig)

    require(
        contact.get("full_name") == "Harry",
        f"NER fallback should recover the sender's first name from a "
        f"fragmented one-token-per-line signature: {contact}",
    )
    require(
        sig["contact"]["full_name"]["method"] == "ner_person",
        f"A NER-recovered field must be tagged with its own method, "
        f"not attributed to a structural match it isn't: {sig['contact']['full_name']}",
    )


def test_ner_fallback_does_not_fabricate_names_from_an_untrustworthy_span() -> None:
    # The generic tail-window span-detection fallback (used when a
    # message isn't a clean single forward -- e.g. no real line breaks
    # at all) is already a weaker last-resort heuristic. Layering NER
    # guesses on top of whatever it lands on produced real false
    # positives while building this feature (an all-caps tech term and
    # a stray two-letter acronym both got mistaken for a person's name).
    # The fallback must stay off entirely outside is_pure_forward, so a
    # message shaped like this keeps its honest "not detected" rather
    # than a confident-looking wrong name.
    text = (
        "Subject: FW: Azure Consultant Sent: Saturday To: Jobs Nvoids "
        "Subject: Azure Consultant You received this email from "
        "harry@itecsus.com via https://jobs.nvoids.com Do Not Change "
        "subject line. Dont remove JD from email. We need TIBCO and Azure "
        "experience. harry@itecsus.com View this job online here"
    )

    sig = parse_email_signature(text=text, sender_email="jobs@jobfynder.com")
    contact = contact_values(sig)

    require(
        "full_name" not in contact,
        f"Must not fabricate a name from a span with no real signature "
        f"content in it, even if NER finds something plausible-looking: {contact}",
    )


def test_deep_quoted_history_still_ignored() -> None:
    # The original Phase 6 protection this module documents: real fresh
    # content above older quoted history must still win -- a stale
    # signature several replies deep must not get attributed to the
    # current sender just because is_pure_forward's threshold exists.
    text = """Thanks, that works for me -- let's move forward.

Jane

On Mon, Aug 24, 2026 at 3:00 PM, Old Sender <old.sender@example.com> wrote:
> Hi Jane,
>
> Please see the details below.
>
> Regards,
> Old Sender
> Legacy Recruiting Inc
> old.sender@example.com
"""

    sig = parse_email_signature(text=text, sender_email="jane@example.com")
    contact = contact_values(sig)

    require(
        contact.get("company_name") != "Legacy Recruiting Inc",
        f"A signature only present in real quoted reply history must stay ignored: {contact}",
    )


def test_empty_text_returns_not_detected() -> None:
    sig = parse_email_signature(text="", sender_email=None)

    require(sig["detected"] is False, "Empty text must never fabricate a detected signature")
    require(sig["contact"] == {}, "Empty text must produce an empty contact dict")


def main() -> int:
    print("HERMES-850 email signature check started")

    test_normal_signoff_signature()
    print("PASS: normal signoff signature (name/title/company/email/linkedin)")

    test_pure_forward_recovers_email_and_website()
    print("PASS: pure single-forward recovers sender email despite the quoted-history boundary")

    test_forwarded_header_block_itself_is_not_mistaken_for_signature()
    print("PASS: forwarded header block's own Subject: line is not mistaken for a job title")

    test_ner_fallback_recovers_fragmented_name()
    print("PASS: NER fallback recovers a name from a fragmented one-token-per-line signature")

    test_ner_fallback_does_not_fabricate_names_from_an_untrustworthy_span()
    print("PASS: NER fallback stays off for a span with no real signature content")

    test_deep_quoted_history_still_ignored()
    print("PASS: a real quoted reply chain's stale signature is still ignored")

    test_empty_text_returns_not_detected()
    print("PASS: empty text does not fabricate a signature")

    print("HERMES-850 email signature check PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"HERMES-850 email signature check FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
