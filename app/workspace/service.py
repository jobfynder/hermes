import json
from pathlib import Path

from app.workspace.models import Workspace, WorkspaceItem

WORKSPACE_PATH = Path("/jobfynder-docs/workspace/workspace.json")


def default_workspace() -> Workspace:
    return Workspace(
        items=[
            WorkspaceItem(
                id="HERMES-310-001",
                item_type="task",
                title="Create Mission Control API",
                status="completed",
                stream="HERMES-310",
                notes="Mission board endpoint created.",
            ),
            WorkspaceItem(
                id="HERMES-310-002",
                item_type="task",
                title="Add Mission Board persistence",
                status="completed",
                stream="HERMES-310",
                notes="Mission board persistence added.",
            ),
            WorkspaceItem(
                id="HERMES-310-003",
                item_type="task",
                title="Add Next Session Brief",
                status="completed",
                stream="HERMES-310",
                notes="Session brief API added.",
            ),
            WorkspaceItem(
                id="HERMES-310-004",
                item_type="task",
                title="Move Mission Control to Workspace",
                status="in_progress",
                stream="HERMES-310",
                notes="Workspace becomes the single source of truth.",
            ),
        ]
    )


def save_workspace(workspace: Workspace) -> None:
    WORKSPACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_PATH.write_text(
        json.dumps(workspace.model_dump(), indent=2),
        encoding="utf-8",
    )


def load_workspace() -> Workspace:
    if not WORKSPACE_PATH.exists():
        workspace = default_workspace()
        save_workspace(workspace)
        return workspace

    data = json.loads(WORKSPACE_PATH.read_text(encoding="utf-8"))
    return Workspace(**data)


def get_workspace() -> Workspace:
    return load_workspace()
