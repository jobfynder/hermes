import json
from typing import Any, Callable

from fastapi import APIRouter, Request

from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse
from app.channels.service import process_channel_intake
from app.security.fastapi_comm import require_comm_signature

from app.providers.whatsapp.service import (
    normalize_whatsapp_payload,
    whatsapp_provider_status,
)
from app.providers.slack.service import (
    normalize_slack_payload,
    slack_provider_status,
)
from app.providers.teams.service import (
    normalize_teams_payload,
    teams_provider_status,
)
from app.providers.google_chat.service import (
    google_chat_provider_status,
    normalize_google_chat_payload,
)


router = APIRouter(prefix="/providers", tags=["Provider Contracts"])


def process_contract_payload(
    payload: dict[str, Any],
    normalizer: Callable[[dict[str, Any]], dict[str, Any]],
) -> ChannelIntakeResponse:
    normalized = normalizer(payload)
    request = ChannelIntakeRequest(**normalized)
    return process_channel_intake(request)


async def signed_payload(request: Request) -> dict[str, Any]:
    body = await require_comm_signature(request)
    return json.loads(body.decode("utf-8"))


@router.get("/whatsapp/status")
def whatsapp_status() -> dict:
    return whatsapp_provider_status()


@router.post("/whatsapp/webhook", response_model=ChannelIntakeResponse)
async def whatsapp_webhook(request: Request) -> ChannelIntakeResponse:
    return process_contract_payload(
        await signed_payload(request),
        normalize_whatsapp_payload,
    )


@router.get("/slack/status")
def slack_status() -> dict:
    return slack_provider_status()


@router.post("/slack/webhook", response_model=ChannelIntakeResponse)
async def slack_webhook(request: Request) -> ChannelIntakeResponse:
    return process_contract_payload(
        await signed_payload(request),
        normalize_slack_payload,
    )


@router.get("/teams/status")
def teams_status() -> dict:
    return teams_provider_status()


@router.post("/teams/webhook", response_model=ChannelIntakeResponse)
async def teams_webhook(request: Request) -> ChannelIntakeResponse:
    return process_contract_payload(
        await signed_payload(request),
        normalize_teams_payload,
    )


@router.get("/google-chat/status")
def google_chat_status() -> dict:
    return google_chat_provider_status()


@router.post("/google-chat/webhook", response_model=ChannelIntakeResponse)
async def google_chat_webhook(request: Request) -> ChannelIntakeResponse:
    return process_contract_payload(
        await signed_payload(request),
        normalize_google_chat_payload,
    )
