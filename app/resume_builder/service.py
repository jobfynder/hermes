from app.resume_builder.feedback import (
    analyze_resume_feedback,
)
from app.resume_builder.quality import (
    analyze_resume_quality,
)
from app.resume_builder.tailoring import (
    analyze_resume_tailoring,
)
from app.resume_builder.taxonomy import (
    normalize_resume_skills,
)
from app.resume_builder.adapters import (
    suggest_bullet,
    suggest_summary,
)
from app.resume_builder.models import (
    ResumeBuilderHealthResponse,
    ResumeBuilderResult,
    ResumeBuilderSafetyPolicy,
    ResumeDocumentInput,
)
from app.resume_builder.safety import evaluate_resume_document


def get_resume_builder_health() -> ResumeBuilderHealthResponse:
    return ResumeBuilderHealthResponse()


def get_resume_builder_policy() -> ResumeBuilderSafetyPolicy:
    return ResumeBuilderSafetyPolicy()

def analyze_resume_document(
    document: ResumeDocumentInput,
) -> ResumeBuilderResult:
    return evaluate_resume_document(document)
