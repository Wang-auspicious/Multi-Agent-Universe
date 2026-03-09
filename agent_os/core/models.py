from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW = "review"
    BLOCKED = "blocked"
    DONE = "done"


@dataclass
class Artifact:
    kind: str
    path: str | None = None
    content: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    repo_path: Path
    goal: str
    constraints: list[str] = field(default_factory=list)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: TaskStatus = TaskStatus.QUEUED
    assigned_executor: str = ""
    artifacts: list[Artifact] = field(default_factory=list)
    summary: str = ""
    cost_tokens: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()
