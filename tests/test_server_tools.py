from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from agent_os.tools.permissions import PermissionPolicy


@pytest.fixture()
def workspace_tmp_path() -> Path:
    root = server.WORKSPACE_ROOT / "tests" / ".tmp_server_tools"
    root.mkdir(parents=True, exist_ok=True)
    tmp_dir = root / f"server-tools-{uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_list_directory_filters_hidden_and_ignore(workspace_tmp_path) -> None:
    (workspace_tmp_path / 'visible.txt').write_text('ok', encoding='utf-8')
    (workspace_tmp_path / 'skip.pyc').write_text('compiled', encoding='utf-8')
    (workspace_tmp_path / '.hidden').write_text('secret', encoding='utf-8')

    original_policy = server.SHELL_POLICY
    server.SHELL_POLICY = PermissionPolicy(repo_path=workspace_tmp_path)
    try:
        result = server._execute_list_directory({
            'path': str(workspace_tmp_path),
            'ignore': ['*.pyc'],
        })
    finally:
        server.SHELL_POLICY = original_policy

    assert result['ok'] is True
    assert result['ignore'] == ['*.pyc']
    entry_names = [entry['name'] for entry in result['entries']]
    assert 'visible.txt' in entry_names
    assert 'skip.pyc' not in entry_names
    assert '.hidden' not in entry_names


def test_run_command_rejects_mutating_command() -> None:
    result = server._execute_run_command({'command': 'git add .'})

    assert result['ok'] is False
    assert result['error_type'] == 'command_not_allowed'


def test_run_command_returns_metadata(workspace_tmp_path, monkeypatch) -> None:
    original_policy = server.SHELL_POLICY
    server.SHELL_POLICY = PermissionPolicy(repo_path=workspace_tmp_path)

    calls: dict[str, object] = {}

    def fake_run(runner, cwd, capture_output, text, timeout, check):
        calls['runner'] = runner
        calls['cwd'] = cwd
        calls['capture_output'] = capture_output
        calls['text'] = text
        calls['timeout'] = timeout
        calls['check'] = check
        return SimpleNamespace(returncode=0, stdout=b'hello\n', stderr=b'')

    monkeypatch.setattr(server.subprocess, 'run', fake_run)
    try:
        result = server._execute_run_command({
            'command': 'python -c "print(123)"',
            'dir_path': str(workspace_tmp_path),
            'timeout_s': 7,
        })
    finally:
        server.SHELL_POLICY = original_policy

    assert result['ok'] is True
    assert result['stdout'] == 'hello'
    assert result['stderr'] == ''
    assert result['timeout_s'] == 7
    assert result['resolved_cwd'] == str(workspace_tmp_path)
    assert result['shell'] in {'powershell', 'bash'}
    assert calls['cwd'] == workspace_tmp_path
    assert calls['capture_output'] is True
    assert calls['text'] is False
    assert calls['timeout'] == 7
    assert calls['check'] is False


def test_run_command_timeout_returns_partial_output(workspace_tmp_path, monkeypatch) -> None:
    original_policy = server.SHELL_POLICY
    server.SHELL_POLICY = PermissionPolicy(repo_path=workspace_tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd='python', timeout=3, output=b'partial', stderr=b'warn')

    monkeypatch.setattr(server.subprocess, 'run', fake_run)
    try:
        result = server._execute_run_command({
            'command': 'python -c "print(123)"',
            'dir_path': str(workspace_tmp_path),
            'timeout_s': 3,
        })
    finally:
        server.SHELL_POLICY = original_policy

    assert result['ok'] is False
    assert result['error_type'] == 'timeout'
    assert result['stdout'] == 'partial'
    assert result['stderr'] == 'warn'


def test_run_command_reports_encoding_warning(workspace_tmp_path, monkeypatch) -> None:
    original_policy = server.SHELL_POLICY
    server.SHELL_POLICY = PermissionPolicy(repo_path=workspace_tmp_path)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=bytes([0xFF]) + b'bad', stderr=b'')

    monkeypatch.setattr(server.subprocess, 'run', fake_run)
    try:
        result = server._execute_run_command({
            'command': 'python -c "print(123)"',
            'dir_path': str(workspace_tmp_path),
        })
    finally:
        server.SHELL_POLICY = original_policy

    assert result['ok'] is True
    assert 'encoding_warning' in result
    assert 'bad' in result['stdout']
