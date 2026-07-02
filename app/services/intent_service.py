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
        "bench",
        "consultants available",
    ]

    question_keywords = [
        "?",
        "can you",
        "please share",
        "any update",
        "status",
        "feedback",
    ]

    if any(keyword in lower_text for keyword in hotlist_keywords):
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