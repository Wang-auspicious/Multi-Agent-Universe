from pathlib import Path

from agent_os.executors.shell_executor import ShellExecutor
from agent_os.tools.permissions import PermissionPolicy
from agent_os.tools.shell import SafeShell


def test_shell_executor_requires_explicit_command() -> None:
    repo = Path('.').resolve()
    shell = SafeShell(repo_path=repo, policy=PermissionPolicy(repo_path=repo))
    ex = ShellExecutor(repo_path=repo, shell=shell)
    result = ex.run(task_id='t1', goal='检索项目目录告诉我有多少个.py文件', constraints=[])
    assert result.ok is False
    assert '只支持显式命令' in result.summary
