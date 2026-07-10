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
