from pydantic import BaseModel, Field
from typing import List


class SessionBrief(BaseModel):
    completed: List[str] = Field(default_factory=list)
    in_progress: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
