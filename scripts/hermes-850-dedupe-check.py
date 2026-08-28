from app.email_parsing.dedupe import compute_body_hash, register_and_check
from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_same_body_different_message_id_flags_exact_duplicate() -> None:
    body = "Job Title: DevOps Engineer\nRequired Skills: AWS, Terraform, Kubernetes\n"

    first = register_and_check(body, "email:msg-1")
    require(not first["is_exact_content_duplicate"], "First delivery must not be flagged as a duplicate")

    second = register_and_check(body, "email:msg-2")
    require(second["is_exact_content_duplicate"], "Second delivery of identical content must be flagged")
    require(
        second["canonical_duplicate_key"] == "email:msg-1",
        "Duplicate must point back at the first-seen message",
    )
    require(
        second["duplicate_group_id"] == compute_body_hash(body),
        "duplicate_group_id must be the content hash itself",
    )


def test_different_body_is_not_a_duplicate() -> None:
    register_and_check("Job Title: Java Developer", "email:msg-3")
    result = register_and_check("Job Title: Python Developer", "email:msg-4")
    require(not result["is_exact_content_duplicate"], "Different content must not be flagged as a duplicate")


def test_intake_preserves_every_source_message() -> None:
    body = "Job Title: Site Reliability Engineer\nRequired Skills: Go, Kubernetes\nLocation: Remote\n"

    first = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="dedupe-source-1",
            content_type="text",
            text=body,
        )
    )
    second = process_channel_intake(
        ChannelIntakeRequest(
            channel="email",
            source_message_id="dedupe-source-2",
            content_type="text",
            text=body,
        )
    )

    require(first.intake_status != "duplicate", "First message must process normally")
    require(
        second.intake_status != "duplicate",
        "A second message_id with identical content must NOT be rejected as a transport duplicate "
        "-- spec 12.1: every source message is preserved, exact-content duplicates are linked, not dropped",
    )
    require(
        second.understanding_result["draft_id"] != first.understanding_result["draft_id"],
        "Exact-content duplicate must still get its own draft (never deleted/merged silently)",
    )


if __name__ == "__main__":
    test_same_body_different_message_id_flags_exact_duplicate()
    test_different_body_is_not_a_duplicate()
    test_intake_preserves_every_source_message()
    print("hermes-850-dedupe-check: all checks passed")
