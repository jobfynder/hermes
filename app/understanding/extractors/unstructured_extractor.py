from pathlib import Path

from app.config import (
    HERMES_UNSTRUCTURED_API_KEY,
    HERMES_UNSTRUCTURED_API_URL,
    HERMES_UNSTRUCTURED_ENABLED,
)
from app.understanding.models import ExtractedText


class UnstructuredFallbackNotConfigured(RuntimeError):
    pass


def is_unstructured_configured() -> bool:
    return bool(
        HERMES_UNSTRUCTURED_ENABLED
        and HERMES_UNSTRUCTURED_API_KEY
        and HERMES_UNSTRUCTURED_API_URL
    )


def extract_with_unstructured(path: str | Path) -> ExtractedText:
    file_path = Path(path)

    if not is_unstructured_configured():
        raise UnstructuredFallbackNotConfigured(
            "Unstructured.io fallback is disabled or missing API configuration."
        )

    # Intentionally not implemented yet.
    # This module is a safe integration placeholder.
    # Actual cloud extraction will be added only after API key, privacy rules,
    # quota controls, and payload limits are confirmed.
    raise NotImplementedError(
        "Unstructured.io fallback transport is not enabled in this build."
    )
