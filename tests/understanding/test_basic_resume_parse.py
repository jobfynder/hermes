from unittest.mock import patch

from app.understanding.models import ExtractedText
from app.understanding.parsers.basic import parse_basic_structured_data
from tests.understanding.test_resume_sections import RESUME


def test_parse_basic_structured_data_includes_resume_sections():
    with patch(
        "app.understanding.parsers.basic.extract_skills",
        return_value=[{"name": "Java", "confidence": 1.0, "method": "exact_phrase"}],
    ):
        structured = parse_basic_structured_data(
            ExtractedText(text=RESUME),
            document_kind="resume",
        )

    assert structured["name"] == "Anubhav Bagri"
    assert structured["phone"] == "+91 89101 45846"
    assert structured["current_title"] == "Associate Software Engineer (Full-time)"
    assert structured["email"] == "anubhavbagri01@gmail.com"
    assert len(structured["experience"]) == 3
    assert structured["education"][0]["year"] == "2023"
    assert any("AZ-900" in cert for cert in structured["certifications"])
