from __future__ import annotations

from agent_os.tools.shell import SafeShell, ToolResult


def run_tests(shell: SafeShell) -> ToolResult:
    return shell.run("pytest -q", timeout_s=180)
