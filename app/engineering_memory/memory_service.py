from pathlib import Path
import json

from app.engineering_memory.generator import generate_daily_memory
from app.engineering_memory.git_service import (
    get_repository_name,
    get_latest_commits,
    get_changed_files,
    get_current_branch,
)
from app.engineering_memory.models import DecisionMemory
from app.engineering_memory.renderer import render_daily_memory
from app.engineering_memory.schemas import GitHubEngineeringMemoryInput


OUTPUT_DIR = Path("/tmp/engineering-memory/daily")


def _branch_from_ref(ref: str | None) -> str:
    if not ref:
        return "unknown"

    return ref.replace("refs/heads/", "")


def _short_sha(value: str | None) -> str:
    if not value:
        return "unknown"

    return value[:7]


def _commit_author_name(author: dict | None) -> str:
    if not author:
        return "unknown"

    return author.get("name") or author.get("username") or author.get("login") or "unknown"


def _collect_changed_files(event: GitHubEngineeringMemoryInput) -> list[str]:
    files: list[str] = []

    for commit in event.commits:
        files.extend([f"added: {path}" for path in commit.added])
        files.extend([f"modified: {path}" for path in commit.modified])
        files.extend([f"removed: {path}" for path in commit.removed])

    return sorted(set(files))


def _generate_memory_from_github_event(event: GitHubEngineeringMemoryInput) -> dict:
    repository_name = (
        event.repository.full_name
        if event.repository and event.repository.full_name
        else "unknown"
    )

    branch = _branch_from_ref(event.ref)
    commit_count = len(event.commits)
    head_sha = _short_sha(event.after)

    sender = "unknown"
    if event.sender:
        sender = event.sender.get("login") or event.sender.get("name") or "unknown"

    completed = [
        "Source: GitHub webhook",
        f"Repository: {repository_name}",
        f"Branch: {branch}",
        f"Head SHA: {head_sha}",
        f"Commit count: {commit_count}",
        f"Triggered by: {sender}",
    ]

    if event.commits:
        completed.append("Commits:")

        for commit in event.commits:
            commit_sha = _short_sha(commit.id)
            message = (commit.message or "").splitlines()[0]
            author = _commit_author_name(commit.author)
            completed.append(f"{commit_sha} {message} — {author}")

    changed_files = _collect_changed_files(event)

    if changed_files:
        completed.append("Changed files:")
        completed.extend(changed_files)

    memory = generate_daily_memory(
        repositories=[repository_name],
        completed=completed,
        decisions=[
            DecisionMemory(
                id="ADR-EMI-002",
                title="Engineering Memory accepts GitHub webhook input",
                status="accepted",
                summary="Hermes can generate engineering memory from GitHub webhook repository, branch, commit, author, and changed-file context.",
            )
        ],
        incidents=[],
        lessons_learned=[
            "Repo-aware engineering memory is more useful than generic repository scanning.",
            "Webhook payloads provide reliable commit, author, branch, and changed-file context.",
        ],
        open_items=[
            "Improve event archive to store full webhook payload.",
            "Add failure alerting for memory automation.",
            "Add deduplication guard for repeated memory commits.",
        ],
        tomorrow_objective="Use repo-aware engineering memory as the default source for GitHub-triggered automation.",
        summary=f"GitHub push event processed for {repository_name} on branch {branch}.",
        status="green",
    )

    return _write_memory(memory)


def _generate_memory_from_current_repo() -> dict:
    repository_name = get_repository_name()
    branch = get_current_branch()
    latest_commits = get_latest_commits(limit=5)
    changed_files = get_changed_files()

    completed = [
        "Source: Hermes local repository scan",
        f"Repository: {repository_name}",
        f"Branch: {branch}",
        "Recent commits:",
        *latest_commits,
    ]

    if changed_files:
        completed.append("Changed files:")
        completed.extend(changed_files)

    memory = generate_daily_memory(
        repositories=[repository_name],
        completed=completed,
        decisions=[
            DecisionMemory(
                id="ADR-EMI-001",
                title="Engineering Memory generated from repository activity",
                status="accepted",
                summary="Hermes generates engineering memory from Git activity and renders it into Markdown.",
            )
        ],
        incidents=[],
        lessons_learned=[
            "Engineering memory should be generated from source activity instead of manually written.",
            "Git metadata provides a reliable starting point for automated daily memory.",
        ],
        open_items=[
            "Add failure alerting for memory automation.",
            "Add deduplication guard for repeated memory commits.",
        ],
        tomorrow_objective="Continue improving Engineering Memory automation.",
        summary="Hermes generated engineering memory from local repository activity.",
        status="green",
    )

    return _write_memory(memory)


def _write_memory(memory) -> dict:
    markdown = render_daily_memory(memory)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / f"{memory.date}.json"
    markdown_path = OUTPUT_DIR / f"{memory.date}.md"

    json_path.write_text(
        json.dumps(memory.model_dump(), indent=2),
        encoding="utf-8",
    )

    markdown_path.write_text(
        markdown,
        encoding="utf-8",
    )

    return {
        "memory": memory.model_dump(),
        "markdown": markdown,
        "files": {
            "json": str(json_path),
            "markdown": str(markdown_path),
        },
    }


def generate_memory_from_current_repo(event: GitHubEngineeringMemoryInput | None = None) -> dict:
    if event and event.repository:
        return _generate_memory_from_github_event(event)

    return _generate_memory_from_current_repo()
