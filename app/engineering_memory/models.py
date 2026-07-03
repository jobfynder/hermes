from pydantic import BaseModel
from typing import List, Optional


class DecisionMemory(BaseModel):
    id: Optional[str] = None
    title: str
    status: str
    summary: str


class IncidentMemory(BaseModel):
    id: Optional[str] = None
    title: str
    summary: str
    root_cause: Optional[str] = None
    resolution: str
    prevention: Optional[str] = None


class DailyEngineeringMemory(BaseModel):
    date: str
    status: str
    summary: str
    repositories: List[str]
    completed: List[str]
    decisions: List[DecisionMemory]
    incidents: List[IncidentMemory]
    lessons_learned: List[str]
    open_items: List[str]
    tomorrow_objective: str