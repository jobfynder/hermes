from typing import Any
from urllib.parse import urlparse

from app.config import (
    HERMES_BRIGHTDATA_API_KEY,
    HERMES_BRIGHTDATA_PROFILE_API_URL,
)


def brightdata_configured() -> bool:
    return bool(HERMES_BRIGHTDATA_API_KEY and HERMES_BRIGHTDATA_PROFILE_API_URL)


def brightdata_provider_status() -> dict[str, Any]:
    return {
        "provider": "brightdata",
        "configured": brightdata_configured(),
        "has_api_key": bool(HERMES_BRIGHTDATA_API_KEY),
        "has_profile_api_url": bool(HERMES_BRIGHTDATA_PROFILE_API_URL),
        "purpose": "public_profile_parsing_only",
        "uses_linkedin_oauth_token": False,
    }


def validate_public_linkedin_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        return {"is_valid": False, "errors": ["invalid_url_scheme"]}

    if "linkedin.com" not in parsed.netloc.lower():
        return {"is_valid": False, "errors": ["not_linkedin_domain"]}

    if "/in/" not in parsed.path:
        return {"is_valid": False, "errors": ["not_public_profile_url"]}

    return {"is_valid": True, "errors": []}


def parse_public_linkedin_profile(url: str) -> dict[str, Any]:
    validation = validate_public_linkedin_url(url)

    if not validation["is_valid"]:
        return {
            "status": "blocked",
            "reason": "invalid_public_linkedin_url",
            "validation": validation,
        }

    if not brightdata_configured():
        return {
            "status": "blocked",
            "reason": "brightdata_not_configured",
            "validation": validation,
            "required_env": [
                "HERMES_BRIGHTDATA_API_KEY",
                "HERMES_BRIGHTDATA_PROFILE_API_URL",
            ],
        }

    return {
        "status": "contract_ready",
        "reason": "brightdata_http_call_not_enabled_until_api_contract_confirmed",
        "public_profile_url": url,
        "validation": validation,
    }
