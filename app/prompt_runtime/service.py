import json
import os
import urllib.error
import urllib.request
from string import Formatter
from uuid import uuid4

from app.prompt_runtime.models import (
    PromptHealthResponse,
    PromptRenderedMessage,
    PromptRunRequest,
    PromptRunResult,
)
from app.prompt_runtime.registry import get_prompt, list_prompts
from app.prompt_runtime.run_log import append_prompt_run, prompt_run_log_dir
from app.prompt_runtime.safety import evaluate_prompt_safety

RUNTIME_VERSION = "hermes_prompt_runtime_v1"
PROVIDER_NAME = "portkey"
DEFAULT_PORTKEY_BASE_URL = "https://api.portkey.ai/v1/chat/completions"


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def portkey_configured() -> bool:
    return bool(os.getenv("PORTKEY_API_KEY"))


def dry_run_default() -> bool:
    return env_bool("HERMES_PROMPT_RUNTIME_DRY_RUN", True)


def _render_template(template: str, variables: dict) -> str:
    rendered = template

    field_names = [
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    ]

    for field_name in field_names:
        value = variables.get(field_name, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=2, sort_keys=True, default=str)
        rendered = rendered.replace("{" + field_name + "}", str(value))

    return rendered


def get_prompt_health() -> PromptHealthResponse:
    registry = list_prompts()
    return PromptHealthResponse(
        runtime_version=RUNTIME_VERSION,
        registry_version=registry.registry_version,
        prompt_count=registry.prompt_count,
        dry_run_default=dry_run_default(),
        portkey_configured=portkey_configured(),
        provider=PROVIDER_NAME,
        run_log_enabled=True,
        run_log_dir=str(prompt_run_log_dir()),
        safety_policy="hermes_prompt_safety_v1",
    )


def render_prompt_messages(prompt_id: str, variables: dict) -> list[PromptRenderedMessage]:
    prompt = get_prompt(prompt_id)
    if not prompt:
        raise ValueError("prompt_not_found")

    return [
        PromptRenderedMessage(
            role="system",
            content=_render_template(prompt.system_template, variables),
        ),
        PromptRenderedMessage(
            role="user",
            content=_render_template(prompt.user_template, variables),
        ),
    ]


def _dry_run_output(prompt_id: str) -> str:
    return (
        f"[dry-run] Prompt {prompt_id} rendered successfully. "
        "No external LLM call was made. Human review is required before use."
    )


def _call_portkey(prompt, messages: list[PromptRenderedMessage]) -> tuple[str, dict]:
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("portkey_api_key_missing")

    base_url = os.getenv("PORTKEY_BASE_URL", DEFAULT_PORTKEY_BASE_URL)
    virtual_key = os.getenv("PORTKEY_VIRTUAL_KEY")
    model = os.getenv("HERMES_PROMPT_DEFAULT_MODEL", prompt.default_model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if virtual_key:
        headers["x-portkey-virtual-key"] = virtual_key

    body = {
        "model": model,
        "messages": [message.model_dump() for message in messages],
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        base_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"portkey_http_{exc.code}:{body_text[:300]}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("portkey_response_missing_choices")

    output = choices[0].get("message", {}).get("content")
    if not output:
        raise RuntimeError("portkey_response_missing_content")

    usage = data.get("usage", {})
    return output, usage


def run_prompt(request: PromptRunRequest) -> PromptRunResult:
    run_id = f"prompt-run-{uuid4()}"
    prompt = get_prompt(request.prompt_id)

    if not prompt:
        result = PromptRunResult(
            runtime_version=RUNTIME_VERSION,
            run_id=run_id,
            prompt_id=request.prompt_id,
            prompt_version="unknown",
            mode_requested=request.mode,
            mode_effective="dry_run",
            provider=PROVIDER_NAME,
            decision="failed",
            reasons=["Prompt id was not found in the registry."],
            risks=["prompt_not_found"],
            next_actions=["Use GET /prompts/registry to inspect supported prompt ids."],
        )
        result.log_path = append_prompt_run(result.model_dump())
        return result

    messages = render_prompt_messages(prompt.prompt_id, request.variables)
    safety = evaluate_prompt_safety(prompt, request)

    if not safety.allowed:
        result = PromptRunResult(
            runtime_version=RUNTIME_VERSION,
            run_id=run_id,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            mode_requested=request.mode,
            mode_effective="dry_run",
            provider=PROVIDER_NAME,
            decision="blocked",
            rendered_messages=messages,
            reasons=["Prompt request blocked by Hermes prompt safety policy."],
            risks=safety.errors,
            next_actions=["Remove unsupported or fabrication-prone instructions and retry."],
            safety=safety,
            metadata=request.metadata,
        )
        result.log_path = append_prompt_run(result.model_dump())
        return result

    effective_mode = "dry_run" if dry_run_default() or request.mode == "dry_run" else "live"

    try:
        if effective_mode == "live":
            output_text, usage = _call_portkey(prompt, messages)
            reasons = ["Prompt executed through Portkey-compatible runtime."]
        else:
            output_text = _dry_run_output(prompt.prompt_id)
            usage = {"external_llm_call": False}
            reasons = ["Dry-run mode is active; rendered prompt was validated but not sent to Portkey."]

        result = PromptRunResult(
            runtime_version=RUNTIME_VERSION,
            run_id=run_id,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            mode_requested=request.mode,
            mode_effective=effective_mode,
            provider=PROVIDER_NAME,
            decision="completed",
            rendered_messages=messages,
            output_text=output_text,
            reasons=reasons,
            risks=safety.warnings,
            next_actions=["Review generated output before publishing, sending, or saving to a user profile."],
            safety=safety,
            usage=usage,
            metadata=request.metadata,
        )
    except RuntimeError as exc:
        result = PromptRunResult(
            runtime_version=RUNTIME_VERSION,
            run_id=run_id,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            mode_requested=request.mode,
            mode_effective=effective_mode,
            provider=PROVIDER_NAME,
            decision="failed",
            rendered_messages=messages,
            reasons=["Prompt execution failed."],
            risks=[str(exc)],
            next_actions=["Check Portkey configuration, provider routing, quota, and network policy."],
            safety=safety,
            metadata=request.metadata,
        )

    result.log_path = append_prompt_run(result.model_dump())
    return result
