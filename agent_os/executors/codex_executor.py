from __future__ import annotations

from pathlib import Path

from agent_os.executors.subprocess_executor import SubprocessCliExecutor


class CodexExecutor(SubprocessCliExecutor):
    name = "codex_cli"
    binary = "codex"
    env_var = "AGENT_OS_CODEX_CMD"
    default_template = "codex exec {prompt}"

    def __init__(self, repo_path: Path, timeout_s: int = 240) -> None:
        super().__init__(repo_path=repo_path, timeout_s=timeout_s)
