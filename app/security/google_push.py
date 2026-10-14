"""Standalone Google Pub/Sub verifier. Not activated on the Gmail route yet."""
import time
import math
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class PushIdentity:
    audience: str
    service_account_email: str

    def __post_init__(self):
        if (not self.audience or self.audience != self.audience.strip()
                or not self.service_account_email.endswith('.iam.gserviceaccount.com')
                or self.service_account_email != self.service_account_email.strip()):
            raise ValueError('Confirmed push audience and service account are required')


def _verify_google_token(token: str, audience: str) -> dict:
    # Lazy imports let the independent implementation be reviewed before rollout.
    # google-auth verifies Google's signature, expiry, audience and issuer.
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token

    class BoundedRequest(GoogleRequest):
        def __call__(self, *args, **kwargs):
            kwargs['timeout'] = 5
            return super().__call__(*args, **kwargs)

    return verify_oauth2_token(token, BoundedRequest(), audience=audience)


def require_google_push(identity: PushIdentity):
    """Create a sync dependency; reject before any request body or handler work.

    Configuration must come from confirmed subscription settings, never headers
    or request payloads. This is independent of Hermes bearer/RBAC credentials.
    """
    def dependency(request: Request) -> dict:
        headers = request.headers.getlist('authorization')
        parts = headers[0].split() if len(headers) == 1 else []
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise HTTPException(status_code=401, detail='Invalid push identity')
        try:
            claims = _verify_google_token(parts[1], identity.audience)
            if (claims.get('aud') != identity.audience
                    or claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}
                    or claims.get('email') != identity.service_account_email
                    or claims.get('email_verified') is not True
                    or not claims.get('sub')
                    or type(claims.get('exp')) not in (int, float)
                    or not math.isfinite(claims['exp'])
                    or not claims['exp'] > time.time()):
                raise ValueError('Invalid claims')
        except Exception:
            # Never expose tokens, claim contents, certificate failures or secrets.
            raise HTTPException(status_code=401, detail='Invalid push identity') from None
        return claims

    return dependency
