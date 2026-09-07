import json
from pathlib import Path

from app.prompt_runtime.models import PromptDefinition, PromptRegistryResponse

REGISTRY_PATH = Path(__file__).with_name("registry.json")
_local: dict[str, PromptDefinition] | None = None


def _load() -> dict[str, PromptDefinition]:
    global _local
    if _local is not None:
        return _local

    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    prompts: dict[str, PromptDefinition] = {}
    for item in data.get("prompts", []):
        definition = PromptDefinition(**item)
        prompts[definition.prompt_id] = definition
    _local = prompts
    return prompts


def get_local_prompt(prompt_id: str) -> PromptDefinition | None:
    return _load().get(prompt_id)


def list_local_prompts() -> list[PromptDefinition]:
    return list(_load().values())


def local_registry() -> PromptRegistryResponse:
    prompts = list_local_prompts()
    return PromptRegistryResponse(
        registry_version="hermes_prompt_registry_v1",
        prompt_count=len(prompts),
        prompts=prompts,
    )
