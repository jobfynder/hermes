from app.prompt_runtime.models import PromptRunRequest
from app.prompt_runtime.registry import get_prompt
from app.prompt_runtime.service import run_prompt


def test_local_profile_extract_prompt_is_registered():
    prompt = get_prompt("jf.onboarding.profile-import.extract")
    assert prompt is not None
    assert "Return ONLY valid JSON" in prompt.system_template
    assert "{{clean_text}}" in prompt.user_template
    assert "{{profile_schema}}" in prompt.user_template


def test_profile_extract_prompt_renders_resume_text():
    result = run_prompt(
        PromptRunRequest(
            prompt_id="jf.onboarding.profile-import.extract",
            variables={
                "clean_text": "Anubhav Bagri\nMobile: +91 89101 45846",
                "profile_schema": '{"name":"string","phone":"string"}',
                "source_type": "resume",
            },
            mode="dry_run",
            source="tests.prompt_runtime",
        )
    )

    assert result.decision == "completed"
    assert result.mode_effective == "dry_run"
    assert result.rendered_messages
    user = result.rendered_messages[1].content
    assert "+91 89101 45846" in user
    assert "Anubhav Bagri" in user
