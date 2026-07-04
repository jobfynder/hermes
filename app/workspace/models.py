from pydantic import BaseModel, Field
from typing import List, Optional


class WorkspaceItem(BaseModel):
    id: str
    item_type: str
    title: str
    status: str = "planned"
    stream: str = "HERMES-310"
    notes: Optional[str] = None


class Workspace(BaseModel):
    name: str = "Hermes Workspace"
    items: List[WorkspaceItem] = Field(default_factory=list)
