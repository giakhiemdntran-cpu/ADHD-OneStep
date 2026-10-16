from dataclasses import dataclass, field
from typing import Any, Dict
from datetime import datetime

CANONICAL_EVENTS = {
    "TASK_CREATED",
    "TASK_UPDATED",
    "TASK_STARTED",
    "TASK_COMPLETED",
    "TASK_MISSED",
    "REMINDER_SENT",
    "SNOOZE",
    "RECALL_SUCCESS",
    "RECALL_FAILURE",
    "USER_FORGOT",
    "USER_REMEMBERED",
    "MEMORY_CHECK",
    "PROMPT_LEVEL_CHANGED",
}

@dataclass
class SuKienHanhVi:
    event_id: str
    user_id: str
    task_id: str
    occurrence_id: str
    timestamp: datetime
    event_type: str
    data: Dict[str, Any] = field(default_factory=dict)
