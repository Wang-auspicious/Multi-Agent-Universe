from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class AgentNote:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class WorkItem:
    title: str
    owner: str
    goal: str
    kind: str = "analysis"
    status: str = "queued"
    item_id: str = field(default_factory=lambda: uuid4().hex[:8])
    result: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CollaborationBoard:
    task_id: str
    goal: str
    constraints: list[str] = field(default_factory=list)
    plan_summary: str = ""
    repo_overview: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    items: list[WorkItem] = field(default_factory=list)
    notes: list[AgentNote] = field(default_factory=list)

    def add_note(self, role: str, content: str) -> None:
        self.notes.append(AgentNote(role=role, content=content))

    def add_item(self, item: WorkItem) -> None:
        self.items.append(item)

    def pending_items(self) -> list[WorkItem]:
        return [item for item in self.items if item.status not in {"done", "blocked"}]

    def completed_items(self) -> list[WorkItem]:
        return [item for item in self.items if item.status == "done"]

    def as_context(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": self.constraints,
            "plan_summary": self.plan_summary,
            "repo_overview": self.repo_overview,
            "conversation_history": self.conversation_history[-10:],
            "items": [item.as_dict() for item in self.items],
            "notes": [asdict(note) for note in self.notes[-12:]],
        }
