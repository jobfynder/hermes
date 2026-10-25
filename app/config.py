import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


HERMES_SERVICE_NAME = os.getenv("HERMES_SERVICE_NAME", "Hermes")
HERMES_VERSION = os.getenv("HERMES_VERSION", "0.2.3")
HERMES_ENV = os.getenv("HERMES_ENV", "development")

# Gmail reconciliation is independent of this unused HTTP push feature.
HERMES_GMAIL_PUSH_ENABLED = env_bool("HERMES_GMAIL_PUSH_ENABLED", False)
HERMES_GMAIL_PUSH_PROJECT_ID = os.getenv("HERMES_GMAIL_PUSH_PROJECT_ID", "")
HERMES_GMAIL_PUSH_SUBSCRIPTION = os.getenv("HERMES_GMAIL_PUSH_SUBSCRIPTION", "")
HERMES_GMAIL_PUSH_AUDIENCE = os.getenv("HERMES_GMAIL_PUSH_AUDIENCE", "")
HERMES_GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL = os.getenv("HERMES_GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL", "")

HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED = env_bool(
    "HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED",
    False,
)

HERMES_LLM_FALLBACK_ENABLED = env_bool(
    "HERMES_LLM_FALLBACK_ENABLED",
    False,
)

HERMES_EMAIL_LLM_FALLBACK_ENABLED = env_bool(
    "HERMES_EMAIL_LLM_FALLBACK_ENABLED",
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

HERMES_LINKEDIN_CLIENT_ID = os.getenv(
    "HERMES_LINKEDIN_CLIENT_ID",
    "",
)

HERMES_LINKEDIN_CLIENT_SECRET = os.getenv(
    "HERMES_LINKEDIN_CLIENT_SECRET",
    "",
)

HERMES_LINKEDIN_REDIRECT_URI = os.getenv(
    "HERMES_LINKEDIN_REDIRECT_URI",
    "",
)

HERMES_BRIGHTDATA_API_KEY = os.getenv(
    "HERMES_BRIGHTDATA_API_KEY",
    "",
)

HERMES_BRIGHTDATA_PROFILE_API_URL = os.getenv(
    "HERMES_BRIGHTDATA_PROFILE_API_URL",
    "",
)

HERMES_COMM_SHARED_SECRET = os.getenv(
    "HERMES_COMM_SHARED_SECRET",
    "",
)

HERMES_COMM_SIGNATURE_MAX_AGE_SECONDS = int(
    os.getenv("HERMES_COMM_SIGNATURE_MAX_AGE_SECONDS", "300")
)



def env_int(name: str, default: int) -> int:
    """Integer env var that falls back to the default on a missing/garbled
    value rather than crashing the process at import time."""
    try:
        return int(os.getenv(name, "").strip())
    except ValueError:
        return default


# Automatic expiry of stale needs_review drafts (app/drafts/expiry.py), run
# by the in-app backfill worker -- no external scheduler involved. A draft
# still in needs_review this many days after it arrived is removed from the
# working table (a full snapshot is archived first). 0 or negative disables.
HERMES_REVIEW_EXPIRY_DAYS = env_int("HERMES_REVIEW_EXPIRY_DAYS", 7)
HERMES_REVIEW_EXPIRY_INTERVAL_SECONDS = max(60, env_int("HERMES_REVIEW_EXPIRY_INTERVAL_SECONDS", 900))
HERMES_REVIEW_EXPIRY_BATCH = min(1000, max(1, env_int("HERMES_REVIEW_EXPIRY_BATCH", 200)))
# How long an expired draft's snapshot stays restorable before it is purged.
HERMES_REVIEW_EXPIRY_ARCHIVE_DAYS = max(1, env_int("HERMES_REVIEW_EXPIRY_ARCHIVE_DAYS", 30))
