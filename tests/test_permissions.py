from pathlib import Path

from agent_os.tools.permissions import PermissionPolicy


def test_permission_blocks_rm() -> None:
    policy = PermissionPolicy(repo_path=Path("."))
    ok, _ = policy.validate_command("rm -rf data")
    assert not ok


def test_permission_blocks_outside_repo() -> None:
    policy = PermissionPolicy(repo_path=Path("."))
    ok, _ = policy.validate_path(Path("C:/Windows/System32"))
    assert not ok
