import os
from typing import Any


HOTLIST_MAILBOX = os.getenv(
    "HERMES_HOTLIST_MAILBOX",
    "hotlists@jobfynder.com",
).strip().lower()

REQUIREMENTS_MAILBOX = os.getenv(
    "HERMES_REQUIREMENTS_MAILBOX",
    "requirements@jobfynder.com",
).strip().lower()


def _extract_addresses(value: Any) -> list[str]:
    addresses: list[str] = []

    if isinstance(value, str):
        for item in value.replace(";", ",").split(","):
            cleaned = item.strip().lower()

            if "<" in cleaned and ">" in cleaned:
                cleaned = (
                    cleaned.split("<", 1)[1]
                    .split(">", 1)[0]
                    .strip()
                )

            if "@" in cleaned:
                addresses.append(cleaned)

        return addresses

    if isinstance(value, dict):
        candidate = (
            value.get("email")
            or value.get("address")
            or value.get("value")
        )

        if candidate:
            addresses.extend(_extract_addresses(candidate))

        return addresses

    if isinstance(value, list):
        for item in value:
            addresses.extend(_extract_addresses(item))

    return addresses


def classify_recipient_mailbox(value: Any) -> str:
    addresses = _extract_addresses(value)
    matched_kinds: set[str] = set()

    for address in addresses:
        if address == HOTLIST_MAILBOX:
            matched_kinds.add("hotlist")

        if address == REQUIREMENTS_MAILBOX:
            matched_kinds.add("job_description")

    if len(matched_kinds) == 1:
        return matched_kinds.pop()

    return "unknown"
