from app.understanding.parsers.contact import extract_phone
from app.understanding.parsers.resume_sections import extract_resume_sections

RESUME = """
Anubhav Bagri Bengaluru, India
LinkedIn: https://linkedin.com/in/anubhavbagri Email: anubhavbagri01@gmail.com
Github: https://github.com/anubhavbagri Mobile: +91 89101 45846
Education
• Manipal University Jaipur Jaipur, India
Bachelor of Technology - Information Technology; GPA: 9.01 July 2019 - June 2023
Relevant Courses: Object Oriented Programming, Data Structures and Algorithms
Skills
• Languages: Java, Dart, SQL, Typescript, Python
Experience
• Shell India Markets Pvt Ltd. Bengaluru, Onsite
Associate Software Engineer (Full-time) August 2023 - Present
◦ Contributed to event-driven architecture using Confluent Kafka.
◦ Optimized CI/CD pipelines (GitHub Actions, Terraform).
• Quriverse Bengaluru, Onsite
Founding App Engineer January 2023 - May 2023
◦ Spearheaded development of a cross-platform mobile application.
• Mindlab Corp. San Jose, Remote
Software Engineering Intern May 2021 - July 2021
◦ Integrated interactive Rive animations.
Achievements
• Microsoft Certified: Azure Fundamentals (AZ-900)
• Best Self Care Hack at Major League Hacking (MLH) Mental Health Hacks II Hackathon.
"""


def test_extract_phone_accepts_indian_mobile():
    assert extract_phone(RESUME) == "+91 89101 45846"


def test_extract_phone_still_accepts_us_number():
    assert extract_phone("Call me at (555) 123-4567") == "(555) 123-4567"


def test_extract_resume_sections_from_jake_style_resume():
    parsed = extract_resume_sections(RESUME)

    assert parsed["name"] == "Anubhav Bagri"
    assert parsed["location"] == "Bengaluru, India"
    assert parsed["phone"] == "+91 89101 45846"
    assert parsed["experience"][0]["company"].startswith("Shell India Markets")
    assert parsed["experience"][0]["title"] == "Associate Software Engineer (Full-time)"
    assert parsed["experience"][0]["endDate"] == "Present"
    assert parsed["experience"][1]["company"] == "Quriverse"
    assert parsed["experience"][2]["company"] == "Mindlab Corp."
    assert parsed["education"][0]["institution"].startswith("Manipal University Jaipur")
    assert "Bachelor of Technology" in (parsed["education"][0]["degree"] or "")
    assert parsed["education"][0]["year"] == "2023"
    assert any("Azure Fundamentals" in cert for cert in parsed["certifications"])
