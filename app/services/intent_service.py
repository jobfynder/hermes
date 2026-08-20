import re


AVAILABILITY_PATTERN = re.compile(
    r"\b(developer|engineer|consultant|candidate|resource|resources|profile|profiles)\b[^.]{0,25}\bavailable\b",
    re.IGNORECASE,
)


def detect_intent(text: str) -> dict:
    cleaned_text = text.strip()
    lower_text = cleaned_text.lower()

    job_keywords = [
        "need",
        "hiring",
        "looking for",
        "requirement",
        "position",
        "contract",
        "full-time",
        "full time",
        "location",
        "job",
        "opening",
        "urgent requirement",
        "client requirement",
    ]

    resume_keywords = [
        "resume",
        "cv",
        "candidate",
        "profile",
        "experience",
        "years",
    ]

    hotlist_keywords = [
        "hotlist",
        "available consultant",
        "available candidates",
        "available candidate",
        "consultants available",
        "consultant available",
        "candidate available",
        "resource available",
        "resources available",
        "bench",
        "on the bench",
        "on bench",
        "rolling off",
        "immediately available",
    ]

    question_keywords = [
        "?",
        "can you",
        "please share",
        "any update",
        "status",
        "feedback",
    ]

    if any(keyword in lower_text for keyword in hotlist_keywords) or AVAILABILITY_PATTERN.search(lower_text):
        return {
            "intent": "HOTLIST",
            "confidence": 0.85,
            "route": "hotlist_parser",
        }

    if any(keyword in lower_text for keyword in resume_keywords):
        return {
            "intent": "RESUME",
            "confidence": 0.80,
            "route": "resume_parser",
        }

    if any(keyword in lower_text for keyword in job_keywords):
        return {
            "intent": "JOB",
            "confidence": 0.90,
            "route": "job_parser",
        }

    if any(keyword in lower_text for keyword in question_keywords):
        return {
            "intent": "QUESTION",
            "confidence": 0.70,
            "route": "no_parser",
        }

    return {
        "intent": "UNKNOWN",
        "confidence": 0.40,
        "route": "manual_review",
    }
