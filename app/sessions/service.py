from uuid import uuid4

from app.runtime.events import emit_event
from app.runtime.jsonl_store import read_json, runtime_path, write_json
from app.sessions.models import ConversationSession, ConversationTransition


_sessions: dict[str, ConversationSession] = {}


def _session_key(channel: str, external_user_id: str) -> str:
    return f"{channel}:{external_user_id}"


def _session_path(channel: str, external_user_id: str):
    safe_key = _session_key(channel, external_user_id).replace(":", "__")
    return runtime_path("sessions", f"{safe_key}.json")


def get_or_create_session(
    channel: str,
    external_user_id: str,
    chat_id: str | None = None,
) -> ConversationSession:
    key = _session_key(channel, external_user_id)

    if key in _sessions:
        return _sessions[key]

    record = read_json(_session_path(channel, external_user_id))
    if record:
        session = ConversationSession(**record)
    else:
        session = ConversationSession(
            session_id=str(uuid4()),
            channel=channel,
            external_user_id=external_user_id,
            chat_id=chat_id,
            state="new",
        )

    _sessions[key] = session
    return session


def save_session(session: ConversationSession) -> ConversationSession:
    key = _session_key(session.channel, session.external_user_id)
    _sessions[key] = session
    write_json(_session_path(session.channel, session.external_user_id), session.model_dump())
    emit_event(
        "conversation.session.updated",
        {
            "session_id": session.session_id,
            "channel": session.channel,
            "external_user_id": session.external_user_id,
            "state": session.state,
            "role": session.role,
            "action": session.action,
        },
    )
    return session


def reset_to_menu(session: ConversationSession) -> ConversationTransition:
    session.state = "menu_shown"
    session.role = None
    session.action = None
    session.expected_input = None
    save_session(session)

    return ConversationTransition(
        session=session,
        should_parse=False,
        response_text="menu",
        reason="menu_shown",
    )


def start_waiting_for_action(
    session: ConversationSession,
    role: str,
    action: str,
) -> ConversationTransition:
    session.role = role
    session.action = action

    if action == "post_hotlist":
        session.state = "waiting_for_hotlist"
        session.expected_input = "hotlist_text_or_file"
        prompt = "Please paste the hotlist or upload the hotlist file."
    elif action == "add_candidate":
        session.state = "waiting_for_candidate"
        session.expected_input = "candidate_text_or_resume"
        prompt = "Please paste candidate details or upload the resume."
    elif action == "post_job_requirement":
        session.state = "waiting_for_job_requirement"
        session.expected_input = "job_requirement_text_or_file"
        prompt = "Please paste the job requirement or upload the JD file."
    elif action == "onboarding_start":
        session.state = "waiting_for_onboarding"
        session.expected_input = "onboarding_profile_text"
        prompt = "Please share your onboarding profile details."
    else:
        session.state = "blocked"
        session.expected_input = None
        prompt = "This action is not supported yet."

    save_session(session)

    return ConversationTransition(
        session=session,
        should_parse=False,
        response_text=prompt,
        reason="waiting_for_business_input",
    )


def handle_business_input(session: ConversationSession) -> ConversationTransition:
    if session.state in {
        "waiting_for_hotlist",
        "waiting_for_candidate",
        "waiting_for_job_requirement",
        "waiting_for_onboarding",
    }:
        return ConversationTransition(
            session=session,
            should_parse=True,
            response_text=None,
            reason="expected_business_input_received",
        )

    return ConversationTransition(
        session=session,
        should_parse=False,
        response_text=(
            "Please choose a Jobfynder action first. Use /start to open the menu."
        ),
        reason="unexpected_free_chat",
    )


def complete_session(session: ConversationSession) -> ConversationSession:
    session.state = "completed"
    save_session(session)
    return session
