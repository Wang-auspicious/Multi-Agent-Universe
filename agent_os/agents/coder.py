from __future__ import annotations

from agent_os.executors.base import ExecutorBase


class CoderAgent:
    def run(
        self,
        executor: ExecutorBase,
        task_id: str,
        goal: str,
        constraints: list[str],
        extra_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        context = {"task_id": task_id, "goal": goal, "constraints": constraints}
        if extra_context:
            context.update(extra_context)
        executor.prepare(context)
        result = executor.run(task_id=task_id, goal=goal, constraints=constraints)
        return {
            "ok": result.ok,
            "summary": result.summary,
            "artifacts": result.artifacts,
            "executor": result.executor,
        }
