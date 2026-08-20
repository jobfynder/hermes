import re
from uuid import uuid4

from app.resume_builder.models import (
    ResumeDocumentInput,
    ResumeFeedbackItem,
    ResumeFeedbackRequest,
    ResumeFeedbackResponse,
    ResumeQualityRequest,
    ResumeTailoringRequest,
)
from app.resume_builder.quality import analyze_resume_quality
from app.resume_builder.tailoring import analyze_resume_tailoring

METRIC_PATTERN = re.compile(r"\d")

WEAK_OPENERS = [
    "responsible for",
    "helped with",
    "worked on",
    "involved in",
    "participated in",
    "assisted with",
    "in charge of",
    "duties included",
    "tasked with",
]

STRONG_VERB_EXAMPLES = [
    "Led",
    "Built",
    "Designed",
    "Delivered",
    "Reduced",
    "Automated",
    "Architected",
]

MIN_BULLET_LENGTH_FOR_CHECK = 25


def _new_item_id() -> str:
    return f"feedback-{uuid4()}"


def _split_bullets(content: str) -> list[str]:
    lines = [line.strip(" \t-•*") for line in content.splitlines()]
    return [line for line in lines if len(line) >= MIN_BULLET_LENGTH_FOR_CHECK]


def _check_unquantified_impact(document: ResumeDocumentInput) -> list[ResumeFeedbackItem]:
    items: list[ResumeFeedbackItem] = []

    for section in document.sections:
        if section.section_type != "experience":
            continue

        for bullet in _split_bullets(section.content):
            if METRIC_PATTERN.search(bullet):
                continue

            items.append(
                ResumeFeedbackItem(
                    id=_new_item_id(),
                    category="unquantified_impact",
                    severity="medium",
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title="Unquantified achievement",
                    current=bullet[:200],
                    suggested_improvement=(
                        "This bullet doesn't include a measurable result. If you have a real number "
                        "(percentage, dollar amount, team size, volume, or time saved), add it. "
                        "Do not invent a figure you can't support."
                    ),
                    why_it_matters=(
                        "Quantified bullets are more credible to recruiters and typically score higher "
                        "in ATS impact scoring than generic statements."
                    ),
                    requires_user_input=True,
                )
            )

    return items


def _check_weak_language(document: ResumeDocumentInput) -> list[ResumeFeedbackItem]:
    items: list[ResumeFeedbackItem] = []

    for section in document.sections:
        if section.section_type not in ("experience", "summary"):
            continue

        lower_content = section.content.lower()

        for phrase in WEAK_OPENERS:
            if phrase not in lower_content:
                continue

            items.append(
                ResumeFeedbackItem(
                    id=_new_item_id(),
                    category="weak_language",
                    severity="low",
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title="Weak opening phrase",
                    current=f"Contains the phrase \"{phrase}\"",
                    suggested_improvement=(
                        f"Replace \"{phrase}\" with a strong action verb such as "
                        f"{', '.join(STRONG_VERB_EXAMPLES[:3])} — only if it accurately describes your role."
                    ),
                    why_it_matters=(
                        "Recruiters scan resumes in seconds. Strong action verbs signal ownership and "
                        "impact faster than passive phrasing."
                    ),
                    requires_user_input=True,
                )
            )
            break

    return items


def _check_incomplete_work_authorization(document: ResumeDocumentInput) -> list[ResumeFeedbackItem]:
    items: list[ResumeFeedbackItem] = []

    for section in document.sections:
        if section.section_type != "other":
            continue

        if "authorization" not in (section.title or "").lower() and "auth" not in section.section_id.lower():
            continue

        content_lower = section.content.lower()
        has_expiry_signal = bool(re.search(r"\b(20\d{2}|expir)", content_lower))
        has_sponsor_signal = "sponsor" in content_lower or "transfer" in content_lower

        if has_expiry_signal and has_sponsor_signal:
            continue

        items.append(
            ResumeFeedbackItem(
                id=_new_item_id(),
                category="incomplete_section",
                severity="high",
                section_id=section.section_id,
                section_type=section.section_type,
                title="Work authorization details incomplete",
                current=section.content[:200] or "(empty)",
                suggested_improvement=(
                    "Add your visa/authorization expiry date, current sponsor (if applicable), and "
                    "transferability status. Only include details you can verify."
                ),
                why_it_matters=(
                    "Recruiters and bench sales teams deprioritize candidates without clear, complete "
                    "work authorization status — this is one of the first filters applied."
                ),
                requires_user_input=True,
            )
        )

    return items


def _quality_items_to_feedback(document: ResumeDocumentInput) -> list[ResumeFeedbackItem]:
    quality = analyze_resume_quality(ResumeQualityRequest(document=document))
    items: list[ResumeFeedbackItem] = []

    for section_type in quality.missing_sections:
        items.append(
            ResumeFeedbackItem(
                id=_new_item_id(),
                category="incomplete_section",
                severity="high",
                section_type=section_type,
                title=f"Missing required section: {section_type}",
                current=None,
                suggested_improvement=f"Add a {section_type} section to your resume.",
                why_it_matters="This section is required for a complete, submission-ready resume.",
                requires_user_input=True,
            )
        )

    for section_id in quality.empty_sections:
        items.append(
            ResumeFeedbackItem(
                id=_new_item_id(),
                category="incomplete_section",
                severity="medium",
                section_id=section_id,
                title="Empty section",
                current=None,
                suggested_improvement="This section exists but has no content yet.",
                why_it_matters="Empty sections reduce your resume's completeness score and look unfinished to reviewers.",
                requires_user_input=True,
            )
        )

    return items


def _check_missing_keywords(document: ResumeDocumentInput, target_job: dict) -> list[ResumeFeedbackItem]:
    if not target_job:
        return []

    resume_payload = {
        "skills": [
            skill
            for section in document.sections
            if section.section_type == "skills"
            for skill in [s.strip() for s in section.content.split(",")]
            if skill
        ],
    }

    tailoring = analyze_resume_tailoring(
        ResumeTailoringRequest(resume=resume_payload, job=target_job)
    )

    items: list[ResumeFeedbackItem] = []

    for skill in tailoring.missing_required_skills:
        items.append(
            ResumeFeedbackItem(
                id=_new_item_id(),
                category="missing_keyword",
                severity="high",
                section_type="skills",
                title=f"Missing required keyword: {skill}",
                current="Not found in your skills list",
                suggested_improvement=(
                    f"'{skill}' is required by the job you're targeting. If you have genuine, verifiable "
                    "experience with it, add it explicitly — recruiters and ATS systems filter on exact "
                    "keyword matches. Do not add it otherwise."
                ),
                why_it_matters="This keyword is explicitly required by the target job description.",
                requires_user_input=True,
                metadata={"skill": skill},
            )
        )

    return items


def analyze_resume_feedback(request: ResumeFeedbackRequest) -> ResumeFeedbackResponse:
    document = request.document

    if not document.sections and not document.source_text:
        return ResumeFeedbackResponse(
            decision="blocked",
            human_review_required=True,
            automatic_apply_allowed=False,
            external_ai_used=False,
            reasons=["Resume content is required for feedback analysis."],
            risks=[],
            next_actions=["Provide resume sections or source text."],
            metadata={**request.metadata, "external_ai_used": False},
        )

    items: list[ResumeFeedbackItem] = []
    items.extend(_quality_items_to_feedback(document))
    items.extend(_check_unquantified_impact(document))
    items.extend(_check_weak_language(document))
    items.extend(_check_incomplete_work_authorization(document))
    items.extend(_check_missing_keywords(document, request.target_job))

    high_priority_count = sum(1 for item in items if item.severity == "high")

    decision = "needs_review" if items else "completed"
    reasons = (
        ["Deterministic resume feedback analysis found items for review."]
        if items
        else ["No deterministic feedback findings - resume passed all automated checks."]
    )

    return ResumeFeedbackResponse(
        decision=decision,
        items=items,
        high_priority_count=high_priority_count,
        pending_count=len(items),
        human_review_required=True,
        automatic_apply_allowed=False,
        external_ai_used=False,
        reasons=reasons,
        risks=[],
        next_actions=[
            "Review each suggestion before applying it.",
            "Never add a skill, metric, or detail you cannot verify.",
        ],
        metadata={
            **request.metadata,
            "item_count": len(items),
            "target_job_provided": bool(request.target_job),
            "external_ai_used": False,
            "prompt_runtime_used": False,
        },
    )
