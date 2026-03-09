from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, check=True, cwd=cwd or ROOT)


def _extract_repo(argv: list[str]) -> str:
    if "--repo" in argv:
        idx = argv.index("--repo")
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return "."


def main() -> None:
    argv = sys.argv[1:]

    if "--dashboard" in argv or "-d" in argv or "--web-dashboard" in argv:
        repo = _extract_repo(argv)
        _run([sys.executable, "-m", "agent_os.apps.workbench", "--repo", repo])
        return

    if "--star-office" in argv:
        backend_dir = ROOT / "Star-Office-UI-1.0.0" / "backend"
        _run([sys.executable, "app.py"], cwd=backend_dir)
        return

    cmd = [sys.executable, "-m", "agent_os.apps.cli", *argv]
    _run(cmd)


if __name__ == "__main__":
    main()
