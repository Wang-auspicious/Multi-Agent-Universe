from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from agent_os.executors.base import ExecutorBase, ExecutorResult


class SubprocessCliExecutor(ExecutorBase):
    binary = ""
    env_var = ""
    default_template = ""

    def __init__(self, repo_path: Path, timeout_s: int = 180) -> None:
        self.repo_path = repo_path
        self.timeout_s = timeout_s
        self._artifacts: list[dict[str, object]] = []

    def prepare(self, context: dict[str, object]) -> None:
        self._artifacts.clear()

    def _build_prompt(self, goal: str, constraints: list[str] | None) -> str:
        constraints = constraints or []
        if not constraints:
            return goal
        lines = "\n".join(f"- {c}" for c in constraints)
        return f"{goal}\n\nConstraints:\n{lines}"

    def _quote(self, value: str) -> str:
        return subprocess.list2cmdline([value])

    def _build_command_text(self, prompt: str) -> str | None:
        custom = os.getenv(self.env_var, "").strip() if self.env_var else ""
        if custom:
            return f"{custom} {self._quote(prompt)}"

        if self.binary and shutil.which(self.binary):
            if self.default_template:
                return self.default_template.format(prompt=self._quote(prompt))
            return f"{self.binary} {self._quote(prompt)}"

        return None

    def healthcheck(self) -> bool:
        custom = os.getenv(self.env_var, "").strip() if self.env_var else ""
        if custom:
            cmd = custom
        elif self.binary and shutil.which(self.binary):
            cmd = self.binary
        else:
            return False

        try:
            probe = f"{cmd} --version"
            proc = subprocess.run(
                probe,
                cwd=self.repo_path,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def run(self, task_id: str, goal: str, constraints: list[str] | None = None) -> ExecutorResult:
        prompt = self._build_prompt(goal, constraints)
        cmd_text = self._build_command_text(prompt)

        if not cmd_text:
            summary = (
                f"{self.name}: CLI unavailable. Install `{self.binary}` or set `{self.env_var}`. "
                "Use `python -m agent_os.apps.cli --healthcheck` to inspect setup."
            )
            artifact = {
                "command": self.binary,
                "ok": False,
                "stdout": "",
                "stderr": "binary not found",
                "exit_code": 127,
                "duration_ms": 0,
                "artifacts": [],
            }
            self._artifacts.append(artifact)
            return ExecutorResult(ok=False, summary=summary, artifacts=self._artifacts, executor=self.name)

        start = time.time()
        try:
            proc = subprocess.run(
                cmd_text,
                cwd=self.repo_path,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
            )
            duration = int((time.time() - start) * 1000)
            artifact = {
                "command": cmd_text,
                "ok": proc.returncode == 0,
                "stdout": (proc.stdout or "").strip(),
                "stderr": (proc.stderr or "").strip(),
                "exit_code": proc.returncode,
                "duration_ms": duration,
                "artifacts": [],
            }
            self._artifacts.append(artifact)
            body = artifact["stdout"] if artifact["stdout"] else artifact["stderr"]
            summary = f"$ {cmd_text}\n{body}".strip()
            return ExecutorResult(ok=proc.returncode == 0, summary=summary, artifacts=self._artifacts, executor=self.name)
        except subprocess.TimeoutExpired:
            duration = int((time.time() - start) * 1000)
            artifact = {
                "command": cmd_text,
                "ok": False,
                "stdout": "",
                "stderr": f"timeout after {self.timeout_s}s",
                "exit_code": 124,
                "duration_ms": duration,
                "artifacts": [],
            }
            self._artifacts.append(artifact)
            return ExecutorResult(ok=False, summary=f"{self.name}: command timeout", artifacts=self._artifacts, executor=self.name)
        except (PermissionError, OSError) as exc:
            duration = int((time.time() - start) * 1000)
            artifact = {
                "command": cmd_text,
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 126,
                "duration_ms": duration,
                "artifacts": [],
            }
            self._artifacts.append(artifact)
            return ExecutorResult(ok=False, summary=f"{self.name}: execution failed ({exc})", artifacts=self._artifacts, executor=self.name)

    def get_artifacts(self) -> list[dict[str, object]]:
        return list(self._artifacts)
