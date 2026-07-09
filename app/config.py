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

HERMES_UNSTRUCTURED_ENABLED = env_bool(
    "HERMES_UNSTRUCTURED_ENABLED",
    False,
)

HERMES_UNSTRUCTURED_API_KEY = os.getenv(
    "HERMES_UNSTRUCTURED_API_KEY",
    "",
)

HERMES_UNSTRUCTURED_API_URL = os.getenv(
    "HERMES_UNSTRUCTURED_API_URL",
    "",
)

HERMES_PUBLIC_WEBHOOK_BASE_URL = os.getenv(
    "HERMES_PUBLIC_WEBHOOK_BASE_URL",
    "",
)

HERMES_TELEGRAM_BOT_TOKEN = os.getenv(
    "HERMES_TELEGRAM_BOT_TOKEN",
    "",
)

HERMES_TELEGRAM_WEBHOOK_SECRET = os.getenv(
    "HERMES_TELEGRAM_WEBHOOK_SECRET",
    "",
)

