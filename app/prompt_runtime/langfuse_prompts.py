import json
import os
import time
import urllib.error
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.prompt_runtime.models import PromptDefinition, PromptRegistryResponse

PROMPTS_PATH = "/api/public/v2/prompts"
DEFAULT_LANGFUSE_BASE_URL = "https://langfuse.jobfynder.com"
DEFAULT_CACHE_SECONDS = 300
DEFAULT_FALLBACK_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_FETCH_CONCURRENCY = 8

_cache: dict = {"registry": None, "prompts": {}, "fetched_at": 0.0}


def langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def _auth_header() -> str:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    token = b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _base_url() -> str:
    return os.getenv("LANGFUSE_BASE_URL", DEFAULT_LANGFUSE_BASE_URL).rstrip("/")


def _cache_seconds() -> int:
    try:
        return int(os.getenv("HERMES_LANGFUSE_PROMPT_CACHE_SECONDS", str(DEFAULT_CACHE_SECONDS)))
    except ValueError:
        return DEFAULT_CACHE_SECONDS


def _fetch_concurrency() -> int:
    try:
        value = int(os.getenv("HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY", str(DEFAULT_FETCH_CONCURRENCY)))
        return max(1, value)
    except ValueError:
        return DEFAULT_FETCH_CONCURRENCY


def _get(path: str) -> dict:
    request = urllib.request.Request(
        f"{_base_url()}{path}",
        headers={
            "Authorization": _auth_header(),
            "User-Agent": "Hermes-PromptRuntime/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _domain_from_owner(owner: str) -> str:
    return (owner or "general").strip().lower() or "general"


def _build_prompt_definition(name: str, detail: dict) -> PromptDefinition | None:
    messages = detail.get("prompt")
    if not isinstance(messages, list):
        return None

    system_content = ""
    user_content = ""

    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_content = content
        elif role == "user":
            user_content = content

    if not system_content or not user_content:
        return None

    config = detail.get("config") or {}
    metadata = config.get("metadata") or {}
    variables = metadata.get("variables") or []
    owner = metadata.get("owner", "general")
    domain_label = metadata.get("domain", "Hermes")
    litellm_cfg = config.get("litellm") or {}

    display_name = name.rsplit(".", 1)[-1].replace("-", " ").title()
    router_alias = litellm_cfg.get("router_alias") or config.get("model")

    return PromptDefinition(
        prompt_id=name,
        name=f"{domain_label}: {display_name}",
        domain=_domain_from_owner(owner),
        version=str(detail.get("version", "1")),
        description=f"{domain_label} prompt sourced from Langfuse ({name}).",
        required_variables=list(variables),
        optional_variables=[],
        system_template=system_content,
        user_template=user_content,
        safety_policy="hermes_prompt_safety_v1",
        default_model=router_alias or DEFAULT_FALLBACK_MODEL,
        status="active",
        metadata={
            "source": "langfuse",
            "langfuse_prompt_name": name,
            "langfuse_version": detail.get("version"),
            "execution_class": metadata.get("execution_class"),
            "runtime_status": metadata.get("runtime_status"),
            "risk": metadata.get("risk"),
            "data_class": metadata.get("data_class"),
            "litellm_router_alias": router_alias,
            "litellm_fallback_alias": litellm_cfg.get("fallback_alias"),
            "evaluation_hooks": metadata.get("evaluation_hooks", []),
        },
    )


def _fetch_prompt_definition(name: str) -> PromptDefinition | None:
    try:
        detail = _get(f"{PROMPTS_PATH}/{name}")
        return _build_prompt_definition(name, detail)
    except Exception:
        return None


def _refresh_cache() -> None:
    listing = _get(f"{PROMPTS_PATH}?limit=100")
    names = [item.get("name") for item in listing.get("data", []) if item.get("name")]

    prompts: dict[str, PromptDefinition] = {}

    # Fetch each prompt's detail concurrently instead of one HTTP round trip
    # at a time. Measured before this fix: ~33s for 38 prompts on a cold
    # cache (sequential N+1) - slow enough that a normal caller timeout
    # (10-30s) could fail even though the fetch would have succeeded given
    # more time. A single failed fetch still only drops that one prompt,
    # same as before - it never aborts the whole refresh.
    with ThreadPoolExecutor(max_workers=_fetch_concurrency()) as executor:
        futures = {executor.submit(_fetch_prompt_definition, name): name for name in names}

        for future in as_completed(futures):
            definition = future.result()
            if definition:
                prompts[definition.prompt_id] = definition

    if prompts:
        _cache["prompts"] = prompts
        _cache["registry"] = PromptRegistryResponse(
            registry_version="hermes_langfuse_prompt_registry_v1",
            prompt_count=len(prompts),
            prompts=list(prompts.values()),
        )
        _cache["fetched_at"] = time.time()


def _ensure_cache() -> None:
    stale = (time.time() - _cache["fetched_at"]) > _cache_seconds()

    if _cache["registry"] is None or stale:
        try:
            _refresh_cache()
        except Exception:
            if _cache["registry"] is None:
                _cache["registry"] = PromptRegistryResponse(
                    registry_version="hermes_langfuse_prompt_registry_v1",
                    prompt_count=0,
                    prompts=[],
                )
                _cache["prompts"] = {}


def list_prompts() -> PromptRegistryResponse:
    if not langfuse_configured():
        return PromptRegistryResponse(
            registry_version="hermes_langfuse_prompt_registry_v1",
            prompt_count=0,
            prompts=[],
        )

    _ensure_cache()
    return _cache["registry"]


def get_prompt(prompt_id: str) -> PromptDefinition | None:
    if not langfuse_configured():
        return None

    _ensure_cache()
    return _cache["prompts"].get(prompt_id)
