import json
from typing import Any

from app.config import HERMES_LLM_FALLBACK_ENABLED
from app.prompt_runtime.models import PromptRunRequest
from app.prompt_runtime.service import run_prompt
from app.runtime.cache import build_cache_key, cache_get, cache_set


def extract_json_object(text: str) -> dict | None:
    """Finds the first balanced {...} block in text and parses it.

    Models frequently wrap JSON in markdown fences and/or append explanatory
    prose after the closing brace, so a simple fence-strip is not reliable -
    this scans for brace balance instead.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return None
                return parsed if isinstance(parsed, dict) else None

    return None


def run_llm_fallback(
    *,
    prompt_id: str,
    variables: dict[str, Any],
    source: str,
    cache_ttl_seconds: int = 0,
) -> dict[str, Any]:
    """Generic confidence-gated LLM fallback executor, shared by every
    HERMES_FALLBACK_LLM capability. The caller is responsible for deciding
    WHETHER to call this (the confidence check) - this function always
    executes the prompt when called, gated only by the global
    HERMES_LLM_FALLBACK_ENABLED master switch.

    Never raises - a fallback failure must not break the deterministic
    response, it just means structured_data stays deterministic-only.
    """
    outcome: dict[str, Any] = {"used": False, "prompt_id": prompt_id}

    if not HERMES_LLM_FALLBACK_ENABLED:
        outcome["reason"] = "llm_fallback_disabled_by_config"
        return outcome

    cache_key = None
    if cache_ttl_seconds > 0:
        cache_key = build_cache_key("llm_fallback", prompt_id, variables)
        cached = cache_get(cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}

    try:
        request = PromptRunRequest(
            prompt_id=prompt_id,
            variables=variables,
            mode="live",
            source=source,
        )
        result = run_prompt(request, force_live=True)

        outcome.update(
            {
                "run_id": result.run_id,
                "decision": result.decision,
                "mode_effective": result.mode_effective,
                "model_used": result.usage.get("model_used") if result.usage else None,
            }
        )

        if result.decision != "completed" or not result.output_text:
            outcome["reason"] = f"llm_fallback_not_completed:{result.decision}"
            return outcome

        parsed = extract_json_object(result.output_text)
        if parsed is None:
            outcome["reason"] = "llm_output_not_valid_json"
            return outcome

        outcome["used"] = True
        outcome["extracted"] = parsed

        if cache_key:
            cache_set(cache_key, outcome, cache_ttl_seconds)

        return outcome
    except Exception as exc:
        outcome["reason"] = f"llm_fallback_error:{exc}"
        return outcome
