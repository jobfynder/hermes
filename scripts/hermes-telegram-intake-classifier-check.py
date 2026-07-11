from app.channels.models import ChannelIntakeRequest
from app.channels.service import detect_document_kind


def classify(text: str | None) -> str:
    request = ChannelIntakeRequest(
        channel="telegram",
        source_message_id="classifier-check",
        content_type="text" if text else "unknown",
        text=text,
    )
    return detect_document_kind(request)


cases = [
    (
        "Production test: Senior Java Developer with 8 years of experience "
        "in Java, Spring Boot, AWS, PostgreSQL, Docker and Kubernetes.",
        "job_description",
    ),
    (
        "We are hiring a Senior Python Engineer with 6 years of experience. "
        "Required skills: Python, AWS, Docker and PostgreSQL.",
        "job_description",
    ),
    (
        "Job opening for a Salesforce Developer. Location: Dallas, TX.",
        "job_description",
    ),
    (
        "Resume - Professional Summary: Java developer with work experience "
        "in Spring Boot and AWS. Education: B.Tech.",
        "resume",
    ),
    (
        "Candidate: Senior Java Developer with 8 years of experience in "
        "Java, Spring Boot, AWS, PostgreSQL and Kubernetes.",
        "resume",
    ),
    (
        "Hotlist: available consultants with Java, AWS and Kubernetes.",
        "hotlist",
    ),
    (
        "Vendor list containing prime vendor and implementation partner details.",
        "vendor_list",
    ),
    (
        "I work in bench sales and manage consultant submissions.",
        "bench_sales_profile",
    ),
    (
        "Hello, can someone help me understand Jobfynder?",
        "plain_message",
    ),
    (
        "",
        "unknown",
    ),
]

for index, (text, expected) in enumerate(cases, start=1):
    actual = classify(text)
    print(f"case={index} expected={expected} actual={actual}")
    if actual != expected:
        raise SystemExit(
            f"FAILED case={index}: expected {expected}, received {actual}"
        )

print("RESULT=TELEGRAM_INTAKE_CLASSIFIER_CHECK_PASSED")
