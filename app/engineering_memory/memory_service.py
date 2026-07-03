from pathlib import Path
import json

from app.engineering_memory.generator import generate_daily_memory
from app.engineering_memory.git_service import (
    get_repository_name,
    get_latest_commits,
    get_changed_files,
    get_current_branch,
)
from app.engineering_memory.models import DecisionMemory, IncidentMemory
from app.engineering_memory.renderer import render_daily_memory


OUTPUT_DIR = Path("/tmp/engineering-memory/daily")


def generate_memory_from_current_repo() -> dict:
    repository_name = get_repository_name()
    branch = get_current_branch()
    latest_commits = get_latest_commits(limit=5)
    changed_files = get_changed_files()

    completed = [
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
            "Connect this service to jobfynder-docs output location.",
            "Add conversation summary input.",
            "Add n8n automation trigger.",
        ],
        tomorrow_objective="Connect Engineering Memory output to jobfynder-docs.",
        summary="Hermes generated an initial engineering memory entry from repository activity.",
        status="green",
    )

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