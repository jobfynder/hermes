import json
import os
import re
import urllib.error
import urllib.request
from uuid import uuid4

from app.prompt_runtime.models import (
    PromptHealthResponse,
    PromptRenderedMessage,
    PromptRunRequest,
    PromptRunResult,
)
from app.prompt_runtime.langfuse_prompts import DEFAULT_FALLBACK_MODEL
from app.prompt_runtime.registry import get_prompt, list_prompts
from app.prompt_runtime.run_log import append_prompt_run, prompt_run_log_dir
from app.prompt_runtime.safety import evaluate_prompt_safety

RUNTIME_VERSION = "hermes_prompt_runtime_v1"
PROVIDER_NAME = "litellm"
DEFAULT_LITELLM_BASE_URL = "https://gateway.jobfynder.com/v1/chat/completions"
DEFAULT_LANGFUSE_BASE_URL = "https://langfuse.jobfynder.com"
TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def litellm_configured() -> bool:
    return bool(os.getenv("LITELLM_API_KEY"))


def langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def dry_run_default() -> bool:
    return env_bool("HERMES_PROMPT_RUNTIME_DRY_RUN", True)


def _render_template(template: str, variables: dict) -> str:
    def _replace(match: "re.Match[str]") -> str:
        field_name = match.group(1)
        value = variables.get(field_name, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=2, sort_keys=True, default=str)
        return str(value)

    return TEMPLATE_VAR_PATTERN.sub(_replace, template)


def get_prompt_health() -> PromptHealthResponse:
    registry = list_prompts()
    return PromptHealthResponse(
        runtime_version=RUNTIME_VERSION,
        registry_version=registry.registry_version,
        registry_source="langfuse",
        prompt_count=registry.prompt_count,
        dry_run_default=dry_run_default(),
        litellm_configured=litellm_configured(),
        langfuse_configured=langfuse_configured(),
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


def _call_litellm_with_model(
    messages: list[PromptRenderedMessage],
    model: str,
) -> tuple[str, dict]:
    api_key = os.getenv("LITELLM_API_KEY")
    if not api_key:
        raise RuntimeError("litellm_api_key_missing")

    base_url = os.getenv("LITELLM_BASE_URL", DEFAULT_LITELLM_BASE_URL)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Hermes-PromptRuntime/1.0",
        "Content-Type": "application/json",
    }

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
        raise RuntimeError(f"litellm_http_{exc.code}:{body_text[:300]}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("litellm_response_missing_choices")

    output = choices[0].get("message", {}).get("content")
    if not output:
        raise RuntimeError("litellm_response_missing_content")

    usage = data.get("usage", {})
    return output, usage


def _call_litellm(prompt, messages: list[PromptRenderedMessage]) -> tuple[str, dict]:
    """Try the prompt's own router alias first; fall back once to the known-working
    default model if the router alias has no healthy deployment on LiteLLM yet."""
    primary_model = prompt.default_model
    fallback_model = os.getenv("HERMES_PROMPT_DEFAULT_MODEL", DEFAULT_FALLBACK_MODEL)

    try:
        output, usage = _call_litellm_with_model(messages, primary_model)
        usage["model_requested"] = primary_model
        usage["model_used"] = primary_model
        return output, usage
    except RuntimeError:
        if primary_model == fallback_model:
            raise

        output, usage = _call_litellm_with_model(messages, fallback_model)
        usage["model_requested"] = primary_model
        usage["model_used"] = fallback_model
        usage["fallback_reason"] = "primary_model_unavailable"
        return output, usage


def _langfuse_usage_details(usage: dict) -> dict[str, int]:
    """Return numeric usage fields using Langfuse's OpenTelemetry conventions."""
    aliases = {
        "prompt_tokens": "input",
        "completion_tokens": "output",
        "total_tokens": "total",
    }
    return {
        aliases.get(key, key): value
        for key, value in usage.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def _langfuse_metadata(result: PromptRunResult, request: PromptRunRequest) -> dict:
    return {
        "run_id": result.run_id,
        "provider": result.provider,
        "mode_requested": result.mode_requested,
        "mode_effective": result.mode_effective,
        "decision": result.decision,
        "correlation_id": request.correlation_id,
        "actor_id": request.actor_id,
        "source": request.source,
        **request.metadata,
    }


def send_langfuse_trace(
    result: PromptRunResult,
    messages: list[PromptRenderedMessage],
    request: PromptRunRequest,
) -> None:
    """Emit a Langfuse v4 OpenTelemetry trace without affecting prompt execution."""
    if not langfuse_configured():
        return

    try:
        # Lazy imports avoid initializing an exporter when tracing is disabled.
        from langfuse import get_client, propagate_attributes

        langfuse = get_client()
        trace_context = {"trace_id": langfuse.create_trace_id(seed=result.run_id)}
        trace_output = {"output_text": result.output_text} if result.output_text else None
        metadata = _langfuse_metadata(result, request)

        with langfuse.start_as_current_observation(
            as_type="span",
            name=result.prompt_id,
            input={"variables": request.variables},
            output=trace_output,
            metadata=metadata,
            trace_context=trace_context,
        ):
            with propagate_attributes(
                trace_name=result.prompt_id,
                user_id=request.actor_id,
                session_id=request.correlation_id,
                tags=["hermes", "prompt_runtime", result.prompt_id],
            ):
                with langfuse.start_as_current_observation(
                    as_type="generation",
                    name=f"{result.prompt_id}.{result.mode_effective}",
                    model=result.usage.get("model_used") if result.usage else None,
                    input=[message.model_dump() for message in messages],
                    output=result.output_text,
                    usage_details=_langfuse_usage_details(result.usage),
                    metadata={
                        "decision": result.decision,
                        "reasons": result.reasons,
                        "risks": result.risks,
                    },
                ):
                    pass
    except Exception:
        pass


def run_prompt(request: PromptRunRequest, force_live: bool = False) -> PromptRunResult:
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
        send_langfuse_trace(result, [], request)
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
        send_langfuse_trace(result, messages, request)
        return result

    effective_mode = "live" if force_live else ("dry_run" if dry_run_default() or request.mode == "dry_run" else "live")

    try:
        if effective_mode == "live":
            output_text, usage = _call_litellm(prompt, messages)
            reasons = ["Prompt executed through LiteLLM-compatible runtime."]
        else:
            output_text = _dry_run_output(prompt.prompt_id)
            usage = {"external_llm_call": False}
            reasons = ["Dry-run mode is active; rendered prompt was validated but not sent to LiteLLM."]

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
            next_actions=["Check LiteLLM configuration, model routing, quota, and network policy."],
            safety=safety,
            metadata=request.metadata,
        )

    result.log_path = append_prompt_run(result.model_dump())
    send_langfuse_trace(result, messages, request)
    return result
