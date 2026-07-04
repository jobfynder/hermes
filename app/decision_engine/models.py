from enum import Enum
from pydantic import BaseModel
from typing import Optional


class DecisionType(str, Enum):
    decision = "decision"
    action = "action"
    task = "task"
    improvement = "improvement"
    bug = "bug"
    risk = "risk"
    research = "research"
    question = "question"


class DecisionPriority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class DecisionStatus(str, Enum):
    detected = "detected"
    accepted = "accepted"
    rejected = "rejected"
    converted = "converted"


class DecisionItem(BaseModel):
    id: str
    title: str
    decision_type: DecisionType = DecisionType.task
    priority: DecisionPriority = DecisionPriority.medium
    status: DecisionStatus = DecisionStatus.detected
    stream: str = "HERMES-402"
    source: str = "conversation"
    confidence: float = 1.0
    notes: Optional[str] = None
