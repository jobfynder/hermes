import json
from functools import lru_cache
from pathlib import Path

from app.prompt_runtime.models import PromptDefinition, PromptRegistryResponse

REGISTRY_PATH = Path(__file__).with_name("registry.json")


@lru_cache(maxsize=1)
def load_prompt_registry() -> PromptRegistryResponse:
    data = json.loads(REGISTRY_PATH.read_text())
    prompts = [PromptDefinition(**item) for item in data.get("prompts", [])]

    return PromptRegistryResponse(
        registry_version=data.get("registry_version", "hermes_prompt_registry_v1"),
        prompt_count=len(prompts),
        prompts=prompts,
    )


def list_prompts() -> PromptRegistryResponse:
    return load_prompt_registry()


def get_prompt(prompt_id: str) -> PromptDefinition | None:
    registry = load_prompt_registry()

    for prompt in registry.prompts:
        if prompt.prompt_id == prompt_id:
            return prompt

    return None
