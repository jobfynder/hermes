import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


HERMES_SERVICE_NAME = os.getenv("HERMES_SERVICE_NAME", "Hermes")
HERMES_VERSION = os.getenv("HERMES_VERSION", "0.2.3")
HERMES_ENV = os.getenv("HERMES_ENV", "development")

HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED = env_bool(
    "HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED",
    False,
)

HERMES_LLM_FALLBACK_ENABLED = env_bool(
    "HERMES_LLM_FALLBACK_ENABLED",
    False,
)
