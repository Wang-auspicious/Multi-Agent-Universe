from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    event_type: str
    task_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class EventTypes:
    TASK_CREATED = "task.created"
    TASK_ASSIGNED = "task.assigned"
    TASK_INTERRUPTED = "task.interrupted"
    AGENT_STARTED = "agent.started"
    PLAN_CREATED = "plan.created"
    WORK_ITEM_STARTED = "work_item.started"
    WORK_ITEM_COMPLETED = "work_item.completed"
    WORKSPACE_UPDATED = "workspace.updated"
    TOOL_CALLED = "tool.called"
    COMMAND_STARTED = "command.started"
    COMMAND_FINISHED = "command.finished"
    DIFF_GENERATED = "diff.generated"
    REVIEW_FAILED = "review.failed"
    TASK_COMPLETED = "task.completed"
