from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from agent_os.executors.base import ExecutorBase, ExecutorResult
from agent_os.tools.shell import SafeShell


_ALLOWED_PREFIXES = (
    "git ",
    "python ",
    "pytest",
    "node ",
    "npm ",
    "pnpm ",
    "rg ",
)


class ShellExecutor(ExecutorBase):
    name = "shell"

    def __init__(self, repo_path: Path, shell: SafeShell) -> None:
        self.repo_path = repo_path
        self.shell = shell
        self._artifacts: list[dict[str, object]] = []

    def prepare(self, context: dict[str, object]) -> None:
        self._artifacts.clear()

    def _looks_like_command(self, goal: str) -> bool:
        stripped = goal.strip()
        return any(stripped.startswith(prefix) for prefix in _ALLOWED_PREFIXES)

    def run(self, task_id: str, goal: str, constraints: list[str] | None = None) -> ExecutorResult:
        if not self._looks_like_command(goal):
            return ExecutorResult(
                ok=False,
                summary="shell 执行器只支持显式命令，不负责理解自然语言任务。请改用 local_agent，或直接输入如 `git status --short`。",
                artifacts=[],
                executor=self.name,
            )

        result = self.shell.run(goal.strip())
        payload = asdict(result)
        payload["command"] = goal.strip()
        self._artifacts.append(payload)
        summary = f"$ {goal.strip()}\n{result.stdout or result.stderr}"
        return ExecutorResult(ok=result.ok, summary=summary, artifacts=self._artifacts, executor=self.name)

    def get_artifacts(self) -> list[dict[str, object]]:
        return list(self._artifacts)
