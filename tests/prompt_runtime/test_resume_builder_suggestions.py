"""Resume-builder summary/bullet suggestions must follow the prompt runtime mode.

They used to be hard-forced to dry_run, so the resume editor only ever got
"[dry-run] Prompt ... rendered successfully" placeholder text even after
HERMES_PROMPT_RUNTIME_DRY_RUN was turned off.
"""

from app.prompt_runtime import service as prompt_service
from app.resume_builder.adapters import suggest_bullet, suggest_summary
from app.resume_builder.models import (
    ResumeBulletSuggestionRequest,
    ResumeSummarySuggestionRequest,
)

SOURCE = "Senior Java developer, 8 years, Spring Boot, AWS, microservices."


def _summary_request():
    return ResumeSummarySuggestionRequest(source_text=SOURCE, target_role="Java Developer")


def _bullet_request():
    return ResumeBulletSuggestionRequest(source_text="Built payment APIs")


def test_summary_stays_dry_run_while_runtime_default_is_dry_run(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "true")

    result = suggest_summary(_summary_request())

    assert result.mode_effective == "dry_run"
    assert result.metadata["external_ai_used"] is False
    assert result.human_review_required is True


def test_summary_is_live_when_runtime_dry_run_is_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "false")
    monkeypatch.setattr(
        prompt_service,
        "_call_litellm",
        lambda prompt, messages: ("Results-driven Java engineer.", {"total_tokens": 10}),
    )

    result = suggest_summary(_summary_request())

    assert result.mode_requested == "live"
    assert result.mode_effective == "live"
    assert result.output_text == "Results-driven Java engineer."
    assert result.metadata["external_ai_used"] is True
    # Suggestions are never auto-applied.
    assert result.human_review_required is True


def test_bullet_is_live_when_runtime_dry_run_is_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "false")
    monkeypatch.setattr(
        prompt_service,
        "_call_litellm",
        lambda prompt, messages: ("Built payment APIs serving 2M requests/day.", {}),
    )

    result = suggest_bullet(_bullet_request())

    assert result.mode_effective == "live"
    assert result.output_text.startswith("Built payment APIs")
    assert result.human_review_required is True
