from pathlib import Path

from agent_os.executors.codex_executor import CodexExecutor


def test_codex_executor_unavailable_returns_hint() -> None:
    ex = CodexExecutor(repo_path=Path("."), timeout_s=1)
    ex.binary = "definitely_not_installed_binary"
    result = ex.run(task_id="t1", goal="fix bug", constraints=[])
    assert result.ok is False
    assert "CLI unavailable" in result.summary
