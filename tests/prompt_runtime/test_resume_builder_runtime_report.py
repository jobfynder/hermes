"""/resume-builder/health and /policy must report the mode the suggestion endpoints really run in.

They used to return fixed defaults (``dry_run`` / ``external_ai_enabled: false``) even in production, where the
summary and bullet suggestions are live, so anyone checking the deployment was told AI was off.
"""

from app.resume_builder.service import (
    get_resume_builder_health,
    get_resume_builder_policy,
)


def test_reports_dry_run_when_the_runtime_is_forced_to_dry_run(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "true")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")

    health = get_resume_builder_health()
    policy = get_resume_builder_policy()

    assert health.prompt_runtime_default_mode == "dry_run"
    assert health.external_ai_enabled is False
    assert policy.prompt_runtime_mode == "dry_run"
    assert policy.external_ai_enabled is False


def test_reports_dry_run_when_no_model_gateway_is_configured(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "false")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)

    assert get_resume_builder_health().external_ai_enabled is False
    assert get_resume_builder_policy().prompt_runtime_mode == "dry_run"


def test_reports_live_when_the_runtime_is_live_and_litellm_is_configured(monkeypatch):
    monkeypatch.setenv("HERMES_PROMPT_RUNTIME_DRY_RUN", "false")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")

    health = get_resume_builder_health()
    policy = get_resume_builder_policy()

    assert health.prompt_runtime_default_mode == "live"
    assert health.external_ai_enabled is True
    assert policy.prompt_runtime_mode == "live"
    assert policy.external_ai_enabled is True
    # Safety guarantees do not depend on the mode.
    assert policy.fabrication_allowed is False
    assert policy.human_review_required is True
    assert policy.automatic_publish_allowed is False
