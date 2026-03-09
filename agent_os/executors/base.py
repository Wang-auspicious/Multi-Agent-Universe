from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ExecutorResult:
    ok: bool
    summary: str
    artifacts: list[dict[str, Any]]
    executor: str = ""


class ExecutorBase:
    name = "base"

    def prepare(self, context: dict[str, Any]) -> None:
        raise NotImplementedError

    def run(self, task_id: str, goal: str, constraints: list[str] | None = None) -> ExecutorResult:
        raise NotImplementedError

    def stream_events(self) -> list[dict[str, Any]]:
        return []

    def get_artifacts(self) -> list[dict[str, Any]]:
        return []

    def cancel(self) -> None:
        return None

    def healthcheck(self) -> bool:
        return True
