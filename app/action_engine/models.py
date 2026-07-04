from enum import Enum
from pydantic import BaseModel
from typing import Optional


class ActionType(str, Enum):
    action = "action"
    decision = "decision"
    task = "task"
    bug = "bug"
    feature = "feature"
    improvement = "improvement"
    idea = "idea"
    research = "research"
    risk = "risk"
    documentation = "documentation"


class ActionPriority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ActionStatus(str, Enum):
    new = "new"
    planned = "planned"
    in_progress = "in_progress"
    blocked = "blocked"
    verify = "verify"
    completed = "completed"
    archived = "archived"


class ActionItem(BaseModel):
    id: str
    title: str
    action_type: ActionType = ActionType.task
    priority: ActionPriority = ActionPriority.medium
    status: ActionStatus = ActionStatus.new
    stream: str = "HERMES-401"
    owner: str = "Hermes"
    notes: Optional[str] = None
