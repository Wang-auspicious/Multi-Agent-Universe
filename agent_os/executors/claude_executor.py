from __future__ import annotations

from pathlib import Path

from agent_os.executors.subprocess_executor import SubprocessCliExecutor


class ClaudeExecutor(SubprocessCliExecutor):
    name = "claude_cli"
    binary = "claude"
    env_var = "AGENT_OS_CLAUDE_CMD"
    default_template = "claude {prompt}"

    def __init__(self, repo_path: Path, timeout_s: int = 240) -> None:
        super().__init__(repo_path=repo_path, timeout_s=timeout_s)
