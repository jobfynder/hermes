CHANNEL_REGISTRY = {
    "telegram": {
        "status": "enabled",
        "supports_text": True,
        "supports_files": True,
    },
    "generic_api": {
        "status": "enabled",
        "supports_text": True,
        "supports_files": True,
    },
    "email": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "whatsapp": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "slack": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "teams": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "google_chat": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "browser_extension": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
    "web_upload": {
        "status": "contract",
        "supports_text": True,
        "supports_files": True,
    },
}


def get_supported_channels() -> dict:
    return {
        "result_version": "hermes_channel_registry_v1",
        "channels": CHANNEL_REGISTRY,
    }
