import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import (
    HERMES_LINKEDIN_CLIENT_ID,
    HERMES_LINKEDIN_CLIENT_SECRET,
    HERMES_LINKEDIN_REDIRECT_URI,
)


LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


def linkedin_oauth_configured() -> bool:
    return bool(
        HERMES_LINKEDIN_CLIENT_ID
        and HERMES_LINKEDIN_CLIENT_SECRET
        and HERMES_LINKEDIN_REDIRECT_URI
    )


def linkedin_provider_status() -> dict:
    return {
        "provider": "linkedin_oauth",
        "configured": linkedin_oauth_configured(),
        "has_client_id": bool(HERMES_LINKEDIN_CLIENT_ID),
        "has_client_secret": bool(HERMES_LINKEDIN_CLIENT_SECRET),
        "redirect_uri": HERMES_LINKEDIN_REDIRECT_URI or None,
        "purpose": "identity_verification_only",
        "scraping_allowed": False,
    }


def build_linkedin_authorization_url(state: str) -> dict:
    if not HERMES_LINKEDIN_CLIENT_ID or not HERMES_LINKEDIN_REDIRECT_URI:
        return {
            "status": "blocked",
            "reason": "linkedin_oauth_not_configured",
        }

    query = urlencode(
        {
            "response_type": "code",
            "client_id": HERMES_LINKEDIN_CLIENT_ID,
            "redirect_uri": HERMES_LINKEDIN_REDIRECT_URI,
            "state": state,
            "scope": "openid profile email",
        }
    )

    return {
        "status": "ready",
        "authorization_url": f"{LINKEDIN_AUTH_URL}?{query}",
        "state": state,
    }


def exchange_linkedin_code(code: str) -> dict:
    if not linkedin_oauth_configured():
        return {
            "status": "blocked",
            "reason": "linkedin_oauth_not_configured",
        }

    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": HERMES_LINKEDIN_REDIRECT_URI,
            "client_id": HERMES_LINKEDIN_CLIENT_ID,
            "client_secret": HERMES_LINKEDIN_CLIENT_SECRET,
        }
    ).encode("utf-8")

    request = Request(
        LINKEDIN_TOKEN_URL,
        data=payload,
        method="POST",
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "linkedin_token_exchange_failed",
            "error": str(exc),
        }

    return {
        "status": "verified",
        "provider": "linkedin_oauth",
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "has_access_token": bool(body.get("access_token")),
        "has_id_token": bool(body.get("id_token")),
        "raw_token_response_stored": False,
    }
