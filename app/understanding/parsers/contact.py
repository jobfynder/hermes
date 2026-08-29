import re


EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

PHONE_PATTERN = re.compile(
    r"(?:(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})"
)

LINKEDIN_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?",
    flags=re.IGNORECASE,
)

WORK_AUTH_PATTERNS = [
    ("US Citizen", r"\b(?:us citizen|u\.s\. citizen|citizen)\b"),
    ("Green Card", r"\b(?:green card|gc|permanent resident)\b"),
    ("H1B", r"\b(?:h1b|h-1b)\b"),
    ("H4 EAD", r"\b(?:h4 ead|h-4 ead)\b"),
    ("L2 EAD", r"\b(?:l2 ead|l-2 ead)\b"),
    ("OPT", r"\b(?:opt|cpt|stem opt)\b"),
    ("TN Visa", r"\b(?:tn visa|tn)\b"),
    # Staffing-industry phrasing for how a candidate/vendor must be able to
    # bill, which recruiters routinely state alongside (or instead of) an
    # actual immigration status -- common in IT staffing postings, absent
    # from the original list, which only covered immigration-status terms.
    # Corp-to-Corp/W2/1099-as-a-billing-arrangement are deliberately left
    # to extract_employment_type() (job_description_fields.py), which
    # already covers that half of the same staffing-lingo overlap.
    ("Independent Visa", r"\bindependent visa\b"),
    ("No Sponsorship", r"\b(?:no sponsorship|without sponsorship|sponsorship not (?:available|provided))\b"),
    ("EAD", r"\b(?:ead|work authorization|work authorised|work authorized)\b"),
]


def extract_email(text: str) -> str | None:
    match = EMAIL_PATTERN.search(text or "")
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    match = PHONE_PATTERN.search(text or "")
    return match.group(0) if match else None


def extract_linkedin_url(text: str) -> str | None:
    match = LINKEDIN_PATTERN.search(text or "")

    if not match:
        return None

    value = match.group(0)

    if not value.lower().startswith("http"):
        value = "https://" + value

    return value.rstrip("/")


def extract_work_authorization(text: str) -> str | None:
    clean_text = text or ""

    for label, pattern in WORK_AUTH_PATTERNS:
        if re.search(pattern, clean_text, flags=re.IGNORECASE):
            return label

    return None
