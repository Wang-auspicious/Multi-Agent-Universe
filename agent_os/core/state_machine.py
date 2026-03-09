from __future__ import annotations

from agent_os.core.models import TaskStatus

_ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING},
    TaskStatus.RUNNING: {TaskStatus.REVIEW, TaskStatus.BLOCKED, TaskStatus.DONE},
    TaskStatus.REVIEW: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.DONE},
    TaskStatus.BLOCKED: {TaskStatus.RUNNING},
    TaskStatus.DONE: set(),
}


class InvalidTransitionError(ValueError):
    pass


def ensure_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransitionError(f"Invalid transition: {current.value} -> {target.value}")
