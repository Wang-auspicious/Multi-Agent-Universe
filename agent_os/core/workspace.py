from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class AgentNote:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TeamMessage:
    sender: str
    recipient: str
    content: str
    item_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    depends_on: list[str] = field(default_factory=list)
    priority: int = 3
    claimed_by: str = ""
    approved: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_ready(self, completed_ids: set[str]) -> bool:
        return all(dep in completed_ids for dep in self.depends_on)


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
    mailbox: list[TeamMessage] = field(default_factory=list)
    lead: str = "planner"
    plan_status: str = "draft"

    def add_note(self, role: str, content: str) -> None:
        self.notes.append(AgentNote(role=role, content=content))

    def send_message(self, sender: str, recipient: str, content: str, item_id: str = "") -> None:
        self.mailbox.append(TeamMessage(sender=sender, recipient=recipient, content=content, item_id=item_id))

    def inbox_for(self, recipient: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = [asdict(msg) for msg in self.mailbox if msg.recipient in {recipient, "all"}]
        return rows[-limit:]

    def add_item(self, item: WorkItem) -> None:
        self.items.append(item)

    def item_by_id(self, item_id: str) -> WorkItem | None:
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    def claim_item(self, item_id: str, role: str) -> WorkItem | None:
        item = self.item_by_id(item_id)
        if item is None:
            return None
        item.claimed_by = role
        return item

    def pending_items(self) -> list[WorkItem]:
        return [item for item in self.items if item.status not in {"done", "blocked"}]

    def completed_items(self) -> list[WorkItem]:
        return [item for item in self.items if item.status == "done"]

    def ready_items(self) -> list[WorkItem]:
        completed_ids = {item.item_id for item in self.completed_items()}
        ready = [
            item for item in self.pending_items()
            if item.owner != "reviewer" and item.status == "queued" and item.is_ready(completed_ids)
        ]
        return sorted(ready, key=lambda item: (item.priority, item.owner, item.title.lower()))

    def approve_plan(self) -> None:
        self.plan_status = "approved"
        for item in self.items:
            item.approved = True

    def as_context(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": self.constraints,
            "plan_summary": self.plan_summary,
            "plan_status": self.plan_status,
            "lead": self.lead,
            "repo_overview": self.repo_overview,
            "conversation_history": self.conversation_history[-10:],
            "items": [item.as_dict() for item in self.items],
            "notes": [asdict(note) for note in self.notes[-12:]],
            "mailbox": [asdict(msg) for msg in self.mailbox[-18:]],
        }

