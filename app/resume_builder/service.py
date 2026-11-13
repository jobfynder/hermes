from app.prompt_runtime.service import dry_run_default, litellm_configured
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


def _runtime_mode() -> str:
    """The mode the suggestion endpoints will actually run in.

    ``live`` only when the prompt runtime is not forced to dry-run and a LiteLLM key is configured, which is the
    same condition under which ``/resume-builder/summary/suggest`` and ``/bullets/suggest`` call a model.
    """
    return "live" if (not dry_run_default() and litellm_configured()) else "dry_run"


def get_resume_builder_health() -> ResumeBuilderHealthResponse:
    mode = _runtime_mode()
    return ResumeBuilderHealthResponse(
        prompt_runtime_default_mode=mode,
        external_ai_enabled=mode == "live",
    )


def get_resume_builder_policy() -> ResumeBuilderSafetyPolicy:
    mode = _runtime_mode()
    return ResumeBuilderSafetyPolicy(
        prompt_runtime_mode=mode,
        external_ai_enabled=mode == "live",
    )


def analyze_resume_document(
    document: ResumeDocumentInput,
) -> ResumeBuilderResult:
    return evaluate_resume_document(document)
