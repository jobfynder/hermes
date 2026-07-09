from typing import Any


def build_start_menu() -> dict[str, Any]:
    return {
        "text": (
            "Welcome to Jobfynder Hermes.\n\n"
            "Please choose what you want to do. Free chat is disabled to protect your data and reduce processing cost."
        ),
        "reply_markup": {
            "keyboard": [
                [{"text": "BSR: Post Hotlist"}],
                [{"text": "BSR: Add Candidate"}],
                [{"text": "Recruiter: Post Job Requirement"}],
                [{"text": "Onboarding: Start"}],
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        },
    }


def map_telegram_text_to_action(text: str) -> dict[str, str] | None:
    cleaned = text.strip().lower()

    mapping = {
        "/start": {
            "type": "menu",
        },
        "onboarding: start": {
            "type": "onboarding",
            "role": "unknown",
            "action": "onboarding_start",
        },
        "bsr: post hotlist": {
            "type": "action",
            "role": "bench_sales_recruiter",
            "action": "post_hotlist",
        },
        "bsr: add candidate": {
            "type": "action",
            "role": "bench_sales_recruiter",
            "action": "add_candidate",
        },
        "recruiter: post job requirement": {
            "type": "action",
            "role": "recruiter",
            "action": "post_job_requirement",
        },
    }

    return mapping.get(cleaned)


def build_blocked_free_chat_message() -> dict[str, Any]:
    return {
        "text": (
            "Please choose one of the available Jobfynder actions first.\n\n"
            "Allowed actions:\n"
            "- BSR: Post Hotlist\n"
            "- BSR: Add Candidate\n"
            "- Recruiter: Post Job Requirement\n"
            "- Onboarding: Start"
        ),
        "reply_markup": build_start_menu()["reply_markup"],
    }
