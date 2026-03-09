from __future__ import annotations

from enum import Enum


class CollaborationState(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    REPAIR = "repair"
    FINALIZE = "finalize"
    DONE = "done"


_ALLOWED: dict[CollaborationState, set[CollaborationState]] = {
    CollaborationState.PLAN: {CollaborationState.EXECUTE},
    CollaborationState.EXECUTE: {CollaborationState.REVIEW},
    CollaborationState.REVIEW: {CollaborationState.REPAIR, CollaborationState.FINALIZE},
    CollaborationState.REPAIR: {CollaborationState.REVIEW},
    CollaborationState.FINALIZE: {CollaborationState.DONE},
    CollaborationState.DONE: set(),
}


class InvalidGraphTransition(ValueError):
    pass


def ensure_graph_transition(current: CollaborationState, target: CollaborationState) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidGraphTransition(f"Invalid collaboration transition: {current.value} -> {target.value}")
