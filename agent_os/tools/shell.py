from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from agent_os.tools.permissions import PermissionPolicy


@dataclass
class ToolResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    artifacts: list[str]
    duration_ms: int


class SafeShell:
    def __init__(self, repo_path: Path, policy: PermissionPolicy) -> None:
        self.repo_path = repo_path
        self.policy = policy

    def run(self, command: str, timeout_s: int = 90) -> ToolResult:
        allowed, reason = self.policy.validate_command(command)
        if not allowed:
            return ToolResult(False, "", reason, 126, [], 0)

        start = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=self.repo_path,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
            duration = int((time.time() - start) * 1000)
            return ToolResult(
                ok=proc.returncode == 0,
                stdout=(proc.stdout or "").strip(),
                stderr=(proc.stderr or "").strip(),
                exit_code=proc.returncode,
                artifacts=[],
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            duration = int((time.time() - start) * 1000)
            return ToolResult(False, "", f"timeout after {timeout_s}s", 124, [], duration)
        except Exception as exc:
            duration = int((time.time() - start) * 1000)
            return ToolResult(False, "", str(exc), 1, [], duration)
