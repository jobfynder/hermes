from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional


class MissionStatus(str, Enum):
    inbox = "inbox"
    planned = "planned"
    in_progress = "in_progress"
    verification = "verification"
    completed = "completed"


class MissionItem(BaseModel):
    id: str
    title: str
    status: MissionStatus
    stream: str = "HERMES-310"
    notes: Optional[str] = None


class MissionBoard(BaseModel):
    module: str = "HERMES-310 Mission Control"
    items: List[MissionItem] = Field(default_factory=list)
