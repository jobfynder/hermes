import json
from typing import Any

from app.prompt_runtime.models import PromptDefinition, PromptRunRequest, PromptSafetyResult

SAFETY_VERSION = "hermes_prompt_safety_v1"

FABRICATION_PATTERNS = [
    "invent",
    "fabricate",
    "make up",
    "fake",
    "add a company",
    "add company",
    "add employer",
    "create employer",
    "add certification",
    "add degree",
    "add years",
    "add experience",
    "add project",
    "pretend",
]

ACTION_PATTERNS = [
    "send email",
    "send message",
    "submit candidate",
    "apply on behalf",
    "approve",
    "delete",
    "charge",
    "payment",
]


def _combined_text(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, default=str).lower()


def evaluate_prompt_safety(
    prompt: PromptDefinition,
    request: PromptRunRequest,
) -> PromptSafetyResult:
    warnings: list[str] = []
    errors: list[str] = []

    combined = _combined_text(
        {
            "variables": request.variables,
            "metadata": request.metadata,
            "source": request.source,
        }
    )

    missing = [
        variable
        for variable in prompt.required_variables
        if variable not in request.variables or request.variables.get(variable) in (None, "")
    ]

    if missing:
        errors.append(f"missing_required_variables:{','.join(missing)}")

    if prompt.domain == "resume_builder":
        source_keys = {"source_text", "resume_text", "parsed_resume", "verified_profile"}
        if not any(request.variables.get(key) for key in source_keys):
            errors.append("resume_source_text_required")

        matched = [pattern for pattern in FABRICATION_PATTERNS if pattern in combined]
        if matched:
            errors.append("resume_fabrication_instruction_detected")
            warnings.append("Resume Builder must not invent facts; ask the user for missing details instead.")

    action_matches = [pattern for pattern in ACTION_PATTERNS if pattern in combined]
    if action_matches:
        warnings.append("Prompt request mentions external action; runtime is draft/human-review only.")

    return PromptSafetyResult(
        allowed=not errors,
        warnings=warnings,
        errors=errors,
        human_review_required=True,
    )
