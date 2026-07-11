from app.channels.models import (
    ChannelIntakeResponse,
    ChannelOutboundMessage,
)


def main() -> None:
    outbound = ChannelOutboundMessage(
        channel="telegram",
        conversation_id="123456",
        text="Welcome to Jobfynder.",
        reply_markup={
            "keyboard": [[{"text": "Onboarding: Start"}]],
            "resize_keyboard": True,
        },
        metadata={
            "workflow": "telegram_onboarding",
            "status": "menu_shown",
        },
    )

    response = ChannelIntakeResponse(
        channel="telegram",
        source_message_id="101",
        intake_status="parsed",
        document_kind="plain_message",
        draft_object_type="draft_channel_note",
        requires_review=False,
        confidence=1.0,
        errors=[],
        duplicate_key="telegram:101",
        outbound_messages=[outbound],
    )

    payload = response.model_dump()

    assert payload["channel"] == "telegram"
    assert len(payload["outbound_messages"]) == 1
    assert payload["outbound_messages"][0]["conversation_id"] == "123456"
    assert payload["outbound_messages"][0]["text"] == "Welcome to Jobfynder."
    assert (
        payload["outbound_messages"][0]["metadata"]["workflow"]
        == "telegram_onboarding"
    )

    empty_response = ChannelIntakeResponse(
        channel="telegram",
        source_message_id="102",
        intake_status="parsed",
        document_kind="plain_message",
        duplicate_key="telegram:102",
    )

    assert empty_response.outbound_messages == []

    print("TELEGRAM_ONBOARDING_OUTBOUND_CONTRACT_PASSED")


if __name__ == "__main__":
    main()
