from pathlib import Path
import shutil

from agent_os.tools.files import list_files, patch_file, patch_history, rollback_patch
from agent_os.tools.permissions import PermissionPolicy


def test_patch_file_applies_diff() -> None:
    repo = Path('tests/.tmp_patch_repo').resolve()
    if repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True, exist_ok=True)
    target = repo / 'demo.py'
    target.write_text('value = 1\n', encoding='utf-8')
    policy = PermissionPolicy(repo_path=repo)

    result = patch_file(target, 'value = 1', 'value = 2', policy)

    assert result.ok is True
    assert 'patched demo.py' in result.stdout
    assert '+value = 2' in result.stdout
    assert 'patch_id=' in result.stdout
    assert target.read_text(encoding='utf-8') == 'value = 2\n'

    history = patch_history(target, policy)
    assert history
    assert history[0]['operation'] == 'patch'

    rollback = rollback_patch(target, policy, entry_id=history[0]['id'])
    assert rollback.ok is True
    assert 'rolled back demo.py' in rollback.stdout
    assert target.read_text(encoding='utf-8') == 'value = 1\n'

    shutil.rmtree(repo, ignore_errors=True)


def test_list_files_skips_heavy_dirs() -> None:
    repo = Path('tests/.tmp_tree_repo').resolve()
    if repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
    (repo / '.git').mkdir(parents=True, exist_ok=True)
    (repo / 'src').mkdir(parents=True, exist_ok=True)
    (repo / 'src' / 'main.py').write_text('print(1)\n', encoding='utf-8')
    (repo / '.git' / 'config').write_text('[core]\n', encoding='utf-8')

    result = list_files(repo, pattern='*', limit=20)

    assert result.ok is True
    assert 'src/main.py' in result.artifacts
    assert '.git/config' not in result.artifacts

    shutil.rmtree(repo, ignore_errors=True)
