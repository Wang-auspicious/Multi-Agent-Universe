from __future__ import annotations

from agent_os.tools.shell import SafeShell, ToolResult


def git_status(shell: SafeShell) -> ToolResult:
    return shell.run("git status --short")


def git_diff(shell: SafeShell) -> ToolResult:
    return shell.run("git diff")
