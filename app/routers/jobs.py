def parse_job_text(text: str):
    cleaned_text = text.strip()

    return {
        "title": extract_title(cleaned_text),
        "summary": cleaned_text[:300],
        "skills": extract_skills(cleaned_text),
        "location": extract_location(cleaned_text),
        "employment_type": extract_employment_type(cleaned_text),
    }