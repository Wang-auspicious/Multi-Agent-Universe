from pathlib import Path
import shutil

from agent_os.apps.workbench import build_buffer_diff, extract_artifact_diff, iter_workspace_files


def test_iter_workspace_files_hides_reference_archives_by_default() -> None:
    base = Path('tests/.tmp_workbench_files_default').resolve()
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    (base / 'agent_os').mkdir(parents=True)
    (base / 'agent_os' / 'main.py').write_text("print('ok')", encoding='utf-8')
    (base / 'codex-main').mkdir()
    (base / 'codex-main' / 'notes.txt').write_text('ignored', encoding='utf-8')

    files = iter_workspace_files(base)

    assert 'agent_os/main.py' in files
    assert 'codex-main/notes.txt' not in files
    shutil.rmtree(base, ignore_errors=True)


def test_iter_workspace_files_can_include_reference_archives() -> None:
    base = Path('tests/.tmp_workbench_files_archives').resolve()
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    (base / 'codex-main').mkdir(parents=True)
    (base / 'codex-main' / 'notes.txt').write_text('keep', encoding='utf-8')

    files = iter_workspace_files(base, include_archives=True)

    assert 'codex-main/notes.txt' in files
    shutil.rmtree(base, ignore_errors=True)


def test_build_buffer_diff_and_extract_artifact_diff() -> None:
    diff = build_buffer_diff(Path('sample.py'), 'alpha\n', 'beta\n')
    artifact = {'stdout': diff}

    assert '--- a/sample.py' in diff
    assert '+beta' in extract_artifact_diff(artifact)
