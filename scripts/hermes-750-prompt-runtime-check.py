from app.prompt_runtime.models import PromptRunRequest
from app.prompt_runtime.registry import get_prompt, list_prompts
from app.prompt_runtime.service import get_prompt_health, run_prompt


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    health = get_prompt_health()
    assert_ok(health.status == "healthy", "prompt runtime health failed")
    assert_ok(health.prompt_count >= 3, "expected prompt registry entries")
    assert_ok(health.dry_run_default is True, "dry-run should be default")

    registry = list_prompts()
    prompt_ids = {prompt.prompt_id for prompt in registry.prompts}
    assert_ok("resume_builder.summary_improve" in prompt_ids, "resume summary prompt missing")
    assert_ok("matching.fit_explanation" in prompt_ids, "matching explanation prompt missing")

    prompt = get_prompt("resume_builder.summary_improve")
    assert_ok(prompt is not None, "resume prompt not found")
    assert_ok(prompt.domain == "resume_builder", "resume prompt domain mismatch")

    result = run_prompt(
        PromptRunRequest(
            prompt_id="resume_builder.summary_improve",
            variables={
                "source_text": "Senior Java developer with Spring Boot and AWS experience.",
                "target_role": "Senior Java Developer",
                "tone": "professional",
                "constraints": "Do not add unsupported facts.",
            },
            mode="dry_run",
            source="script_check",
        )
    )

    assert_ok(result.decision == "completed", f"dry-run prompt failed: {result.decision}")
    assert_ok(result.mode_effective == "dry_run", "dry-run mode not effective")
    assert_ok(result.usage.get("external_llm_call") is False, "dry-run made external call")

    blocked = run_prompt(
        PromptRunRequest(
            prompt_id="resume_builder.summary_improve",
            variables={
                "source_text": "Java developer.",
                "constraints": "Invent a certification and make up employer names.",
            },
            mode="dry_run",
            source="script_check",
        )
    )

    assert_ok(blocked.decision == "blocked", "fabrication instruction was not blocked")
    assert_ok(
        "resume_fabrication_instruction_detected" in blocked.safety.errors,
        "fabrication safety error missing",
    )

    missing = run_prompt(
        PromptRunRequest(
            prompt_id="resume_builder.summary_improve",
            variables={},
            mode="dry_run",
            source="script_check",
        )
    )

    assert_ok(missing.decision == "blocked", "missing source text was not blocked")

    print("HERMES-750 prompt runtime foundation checks passed.")


if __name__ == "__main__":
    main()
