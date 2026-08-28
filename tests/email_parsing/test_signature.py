"""Fixture suite for app/email_parsing/signature.py.

Covers the deterministic signature detection/extraction pipeline in
isolation. See test_signature_regression.py for proof that adding this
module didn't change existing hotlist/job_description email parsing.
"""

from app.email_parsing.signature import parse_email_signature


def _value(result: dict, field: str):
    entry = result["contact"].get(field)
    return entry["value"] if entry else None


class TestPlainTextSignature:
    def test_plain_text_signature_extracts_core_fields(self):
        text = (
            "Hi team,\n\n"
            "Please see the attached hotlist for this week.\n\n"
            "Best regards,\n"
            "John Smith\n"
            "Senior Technical Recruiter\n"
            "ABC Staffing Inc\n"
            "john@abcstaffing.com\n"
            "P: (214) 555-1234\n"
        )
        result = parse_email_signature(text)

        assert result["detected"] is True
        assert result["method"] == "signoff_marker"
        assert _value(result, "full_name") == "John Smith"
        assert _value(result, "job_title") == "Senior Technical Recruiter"
        assert _value(result, "company_name") == "ABC Staffing Inc"
        assert _value(result, "email") == "john@abcstaffing.com"
        assert _value(result, "phone") == "+12145551234"
        assert result["confidence"] >= 0.70
        assert result["requires_review"] is False


class TestHtmlDerivedSignature:
    """By the time text reaches this parser it has already gone through
    HTML->text conversion upstream (markitdown, per requirements.txt) --
    these fixtures model the residual artifacts that survive that step
    (stray tags, entities, alt-text placeholders), not raw <html> markup.
    """

    def test_html_derived_signature_survives_residual_markup(self):
        text = (
            "Thanks,<br>\n"
            "Priya Menon<br>\n"
            "IT Recruiter | Global Tech Solutions LLC<br>\n"
            "priya.menon@globaltech.com&nbsp;\n"
        )
        result = parse_email_signature(text)

        assert result["detected"] is True
        assert _value(result, "email") == "priya.menon@globaltech.com"

    def test_malformed_html_does_not_crash_and_does_not_hallucinate(self):
        text = (
            "Regards,\n"
            "<div><span>Alex <b>Rivera</b\n"
            "<img src=cid:image001.png@01D12345 alt=\"logo\">\n"
            "Talent Partner\n"
        )
        result = parse_email_signature(text)

        # Must not raise, and must not invent an email/phone that isn't there.
        assert result["detected"] is True
        assert _value(result, "email") is None
        assert _value(result, "phone") is None
        assert _value(result, "mobile") is None

    def test_logo_image_placeholder_is_ignored_not_captured_as_a_field(self):
        text = (
            "Best,\n"
            "Dana Lee\n"
            "[Company Logo]\n"
            "Recruiter\n"
            "dana.lee@example.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "full_name") == "Dana Lee"
        for field in result["contact"].values():
            assert "[Company Logo]" not in (field.get("raw") or "")


class TestRoleSpecificSignatures:
    def test_recruiter_signature(self):
        text = (
            "Regards,\n"
            "Michael Chen\n"
            "Technical Recruiter\n"
            "Peak Consulting Group\n"
            "michael.chen@peakconsulting.com\n"
            "M: 469-555-7890\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "job_title") == "Technical Recruiter"
        assert _value(result, "mobile") == "+14695557890"

    def test_consultant_signature(self):
        text = (
            "Thank you,\n"
            "Sara Ahmed\n"
            "Senior Consultant\n"
            "sara.ahmed@example.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "full_name") == "Sara Ahmed"
        assert _value(result, "job_title") == "Senior Consultant"

    def test_staffing_company_signature(self):
        text = (
            "Best,\n"
            "Robert Diaz\n"
            "Account Manager\n"
            "Prime Staffing Solutions Inc\n"
            "robert.diaz@primestaffing.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "company_name") == "Prime Staffing Solutions Inc"


class TestClientVariants:
    def test_gmail_style_signature(self):
        text = (
            "Sounds good, let's connect tomorrow.\n\n"
            "--\n"
            "Emily Zhao\n"
            "Recruiter, Client Engagement\n"
            "emily.zhao@gmail.com\n"
        )
        result = parse_email_signature(text)

        assert result["detected"] is True
        assert result["method"] == "signoff_marker"
        assert _value(result, "email") == "emily.zhao@gmail.com"

    def test_outlook_style_signature_with_disclaimer(self):
        text = (
            "Sincerely,\n"
            "Tom Walsh\n"
            "Director of Recruiting\n"
            "Walsh Partners LLC\n"
            "tom.walsh@walshpartners.com\n"
            "O: 972-555-2200\n\n"
            "This email and any attachments are confidential and may be "
            "privileged. If you are not the intended recipient, please "
            "delete this message.\n"
        )
        result = parse_email_signature(text)

        assert "disclaimer_removed" in result["warnings"]
        assert "confidential" not in result["raw"].lower()
        assert _value(result, "phone") == "+19725552200"


class TestPhoneHandling:
    def test_phone_with_extension(self):
        text = (
            "Best,\n"
            "Carla Nguyen\n"
            "carla.nguyen@example.com\n"
            "Phone: (214) 555-9000 ext. 204\n"
        )
        result = parse_email_signature(text)

        phone = result["contact"]["phone"]
        assert phone["value"] == "+12145559000"
        assert phone["extension"] == "204"

    def test_multiple_phone_numbers_split_phone_and_mobile(self):
        text = (
            "Best,\n"
            "Derek Osei\n"
            "derek.osei@example.com\n"
            "O: 214-555-1111\n"
            "M: 469-555-2222\n"
        )
        result = parse_email_signature(text)

        assert result["contact"]["phone"]["value"] == "+12145551111"
        assert result["contact"]["mobile"]["value"] == "+14695552222"

    def test_international_phone_number(self):
        text = (
            "Regards,\n"
            "Nina Patel\n"
            "nina.patel@example.com\n"
            "Phone: +44 20 7946 0958\n"
        )
        result = parse_email_signature(text)

        assert result["contact"]["phone"]["value"] == "+442079460958"

    def test_fax_number_is_not_captured_as_phone(self):
        text = (
            "Best,\n"
            "Owen Grant\n"
            "owen.grant@example.com\n"
            "Fax: 214-555-3333\n"
        )
        result = parse_email_signature(text)

        assert "phone" not in result["contact"]
        assert "mobile" not in result["contact"]


class TestLinksAndAddress:
    def test_linkedin_url(self):
        text = (
            "Best,\n"
            "John Smith\n"
            "linkedin.com/in/johnsmith\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "linkedin_url") == "https://linkedin.com/in/johnsmith"

    def test_website(self):
        text = (
            "Best,\n"
            "John Smith\n"
            "ABC Staffing Inc\n"
            "www.abcstaffing.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "website") == "https://www.abcstaffing.com"

    def test_website_excludes_linkedin_and_tracking_links(self):
        text = (
            "Best,\n"
            "John Smith\n"
            "linkedin.com/in/johnsmith\n"
            "https://click.mailchi.mp/track/abc123\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "website") is None

    def test_postal_address_city_state(self):
        text = (
            "Best,\n"
            "John Smith\n"
            "Dallas, TX 75201\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "city") == "Dallas"
        assert _value(result, "state") == "TX"
        assert _value(result, "postal_code") == "75201"


class TestNegativeAndEdgeCases:
    def test_no_signature_present(self):
        text = "Hey, can you send me the update by end of day? Thanks in advance for the quick turnaround on this one."
        result = parse_email_signature(text)

        assert result["detected"] is False
        assert result["contact"] == {}
        assert result["confidence"] == 0.0
        assert result["requires_review"] is True

    def test_short_signature_still_detected(self):
        text = "Sounds good.\n\nBest,\nJohn\n"
        result = parse_email_signature(text)

        assert result["detected"] is True
        # A bare first name only isn't enough signal to be confident.
        assert result["confidence"] < 0.70

    def test_confidentiality_disclaimer_alone_is_not_a_contact(self):
        text = (
            "Confidentiality Notice: This email and any files transmitted "
            "with it are confidential and intended solely for the use of "
            "the individual to whom they are addressed.\n"
        )
        result = parse_email_signature(text)

        assert result["contact"] == {}

    def test_long_legal_disclaimer_is_stripped(self):
        text = (
            "Thanks,\n"
            "Bill Ortiz\n"
            "bill.ortiz@example.com\n\n"
            "CONFIDENTIALITY NOTICE\n"
            "This message and any attachments are intended solely for "
            "the addressee and may contain confidential information. "
            "If you have received this message in error, please notify "
            "the sender immediately and delete all copies. Any "
            "unauthorized review, use, disclosure or distribution is "
            "prohibited. This company accepts no liability for any "
            "damage caused by any virus transmitted by this email.\n"
        )
        result = parse_email_signature(text)

        assert "CONFIDENTIALITY NOTICE" not in result["raw"]
        assert _value(result, "email") == "bill.ortiz@example.com"

    def test_mobile_sent_from_iphone_marker(self):
        text = "Yes that works for me.\n\nSent from my iPhone\n"
        result = parse_email_signature(text)

        assert result["detected"] is True
        assert result["method"] == "mobile_signature_marker"
        assert result["contact"] == {}

    def test_signature_containing_a_different_email_than_sender(self):
        text = (
            "Best,\n"
            "John Smith\n"
            "john.personal@gmail.com\n"
        )
        result = parse_email_signature(text, sender_email="john.smith@abcstaffing.com")

        assert result["sender_email"] == "john.smith@abcstaffing.com"
        assert result["signature_email"] == "john.personal@gmail.com"
        assert "signature_email_differs_from_sender" in result["warnings"]
        # The authoritative sender identity is reported, never overwritten.
        assert result["sender_email"] != result["signature_email"]


class TestQuotedAndForwardedMail:
    def test_forwarded_email_only_scans_top_message(self):
        text = (
            "Best,\n"
            "Alice Kim\n"
            "alice.kim@example.com\n\n"
            "---------- Forwarded message ---------\n"
            "From: Bob Lee <bob.lee@other.com>\n"
            "Date: Mon, Aug 24, 2026 at 9:36 AM\n"
            "Subject: Fwd: Requirement\n\n"
            "Regards,\n"
            "Bob Lee\n"
            "bob.lee@other.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "email") == "alice.kim@example.com"
        assert result["quoted_signature_ignored"] is True

    def test_replied_email_only_scans_top_message(self):
        text = (
            "Sounds great, thanks!\n\n"
            "Best,\n"
            "Carol Diaz\n"
            "carol.diaz@example.com\n\n"
            "On Mon, Aug 24, 2026 at 9:00 AM, Dave Park <dave.park@x.com> "
            "wrote:\n"
            "> Best,\n"
            "> Dave Park\n"
            "> dave.park@x.com\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "email") == "carol.diaz@example.com"

    def test_nested_email_thread_ignores_all_quoted_signatures(self):
        text = (
            "Best,\n"
            "Grace Lin\n"
            "grace.lin@example.com\n\n"
            "On Fri, Aug 21, 2026, Henry Osei <henry.osei@y.com> wrote:\n"
            "> Regards,\n"
            "> Henry Osei\n"
            ">\n"
            "> On Thu, Aug 20, 2026, Ivy Chen <ivy.chen@z.com> wrote:\n"
            "> > Thanks,\n"
            "> > Ivy Chen\n"
        )
        result = parse_email_signature(text)

        assert _value(result, "email") == "grace.lin@example.com"
        assert result["quoted_signature_ignored"] is True

    def test_include_quoted_history_opt_in(self):
        text = (
            "No signature here.\n\n"
            "On Mon wrote:\n"
            "> Best,\n"
            "> Jamie Fox\n"
            "> jamie.fox@example.com\n"
        )
        default_result = parse_email_signature(text)
        opt_in_result = parse_email_signature(text, include_quoted_history=True)

        assert default_result["detected"] is False
        assert opt_in_result["detected"] is True
        assert _value(opt_in_result, "email") == "jamie.fox@example.com"


class TestGuardrails:
    def test_never_uses_llm(self):
        result = parse_email_signature("Best,\nJohn Smith\njohn@example.com\n")
        assert result["parser"]["uses_llm"] is False

    def test_empty_text_is_handled(self):
        result = parse_email_signature("")
        assert result["detected"] is False
        assert result["contact"] == {}
