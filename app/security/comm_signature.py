import hashlib
import hmac
import time

from app.config import (
    HERMES_COMM_SHARED_SECRET,
    HERMES_COMM_SIGNATURE_MAX_AGE_SECONDS,
)


def build_comm_signature(timestamp: str, body: bytes) -> str:
    payload = timestamp.encode("utf-8") + b"." + body

    return hmac.new(
        HERMES_COMM_SHARED_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def verify_comm_signature(
    timestamp: str | None,
    signature: str | None,
    body: bytes,
) -> tuple[bool, str | None]:
    if not HERMES_COMM_SHARED_SECRET:
        return False, "comm_shared_secret_not_configured"

    if not timestamp or not signature:
        return False, "comm_signature_headers_missing"

    try:
        request_time = int(timestamp)
    except ValueError:
        return False, "comm_timestamp_invalid"

    now = int(time.time())

    if abs(now - request_time) > HERMES_COMM_SIGNATURE_MAX_AGE_SECONDS:
        return False, "comm_request_expired"

    expected = build_comm_signature(timestamp, body)

    if not hmac.compare_digest(expected, signature):
        return False, "comm_signature_invalid"

    return True, None
