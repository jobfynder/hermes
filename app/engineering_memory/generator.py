from datetime import datetime

from app.engineering_memory.models import (
    DailyEngineeringMemory,
    DecisionMemory,
    IncidentMemory,
)


def generate_daily_memory(
    repositories: list[str],
    completed: list[str],
    decisions: list[DecisionMemory],
    incidents: list[IncidentMemory],
    lessons_learned: list[str],
    open_items: list[str],
    tomorrow_objective: str,
    summary: str,
    status: str = "green",
) -> DailyEngineeringMemory:

    return DailyEngineeringMemory(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        status=status,
        summary=summary,
        repositories=repositories,
        completed=completed,
        decisions=decisions,
        incidents=incidents,
        lessons_learned=lessons_learned,
        open_items=open_items,
        tomorrow_objective=tomorrow_objective,
    )