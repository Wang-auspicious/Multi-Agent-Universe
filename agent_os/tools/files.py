from __future__ import annotations

import difflib
import fnmatch
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_os.tools.permissions import PermissionPolicy
from agent_os.tools.shell import ToolResult


IGNORED_DIRS = {
    ".git",
    ".idea",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".pytest_tmp",
    "dist",
    "build",
}
IGNORED_PREFIXES = ("pytest-cache-files-",)
TEXT_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc", ".pyo", ".zip", ".pdf", ".sqlite", ".db"}
PATCH_HISTORY_DIR = "data/patch_history"


def _diff_text(old: str, new: str, path: Path) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            lineterm="",
        )
    )


def _iter_repo_files(repo_path: Path, pattern: str = "*") -> list[Path]:
    repo_path = repo_path.resolve()
    matched: list[Path] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRS and not any(d.startswith(prefix) for prefix in IGNORED_PREFIXES)
        ]
        base = Path(root)
        for name in files:
            rel = (base / name).relative_to(repo_path)
            rel_text = rel.as_posix()
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_text, pattern):
                matched.append(base / name)
    matched.sort(key=lambda p: p.as_posix().lower())
    return matched


def _history_dir_for(path: Path, policy: PermissionPolicy) -> Path:
    return policy.repo_path.resolve() / PATCH_HISTORY_DIR / path.relative_to(policy.repo_path.resolve()).parent


def _record_patch_history(path: Path, before: str, after: str, operation: str, policy: PermissionPolicy) -> str | None:
    if before == after:
        return None
    diff = _diff_text(before, after, path)
    entry_id = uuid4().hex[:12]
    entry = {
        "id": entry_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "path": str(path.relative_to(policy.repo_path.resolve()).as_posix()),
        "before": before,
        "after": after,
        "diff": diff,
    }
    history_dir = _history_dir_for(path, policy)
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{path.name}.jsonl"
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry_id


def patch_history(path: Path, policy: PermissionPolicy, limit: int = 20) -> list[dict[str, str]]:
    ok, _ = policy.validate_path(path)
    if not ok:
        return []
    history_path = _history_dir_for(path, policy) / f"{path.name}.jsonl"
    if not history_path.exists():
        return []
    rows: list[dict[str, str]] = []
    with history_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                data = json.loads(line)
            except Exception:
                continue
            rows.append(
                {
                    "id": str(data.get("id", "")),
                    "timestamp": str(data.get("timestamp", "")),
                    "operation": str(data.get("operation", "")),
                    "path": str(data.get("path", "")),
                    "before": str(data.get("before", "")),
                    "after": str(data.get("after", "")),
                    "diff": str(data.get("diff", "")),
                }
            )
    return rows[-limit:][::-1]


def rollback_patch(path: Path, policy: PermissionPolicy, entry_id: str | None = None) -> ToolResult:
    ok, reason = policy.validate_path(path)
    if not ok:
        return ToolResult(False, "", reason, 1, [], 0)
    history_path = _history_dir_for(path, policy) / f"{path.name}.jsonl"
    if not history_path.exists():
        return ToolResult(False, "", f"No patch history for {path.name}", 1, [], 0)
    entries: list[dict[str, object]] = []
    with history_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    target = None
    if entry_id:
        target = next((item for item in reversed(entries) if str(item.get("id")) == entry_id), None)
    elif entries:
        target = entries[-1]
    if not target:
        return ToolResult(False, "", f"Patch entry not found for {path.name}", 1, [], 0)
    before = path.read_text(encoding="utf-8-sig") if path.exists() and path.is_file() else ""
    restored = str(target.get("before", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(restored, encoding="utf-8")
    rollback_id = _record_patch_history(path, before, restored, "rollback", policy)
    diff = _diff_text(before, restored, path)
    stdout = f"rolled back {path.name}"
    if entry_id:
        stdout += f"\nentry_id={entry_id}"
    if rollback_id:
        stdout += f"\nrollback_id={rollback_id}"
    if diff:
        stdout += f"\n{diff}"
    return ToolResult(True, stdout, "", 0, [str(path)], 0)


def read_file(path: Path, policy: PermissionPolicy) -> ToolResult:
    ok, reason = policy.validate_path(path)
    if not ok:
        return ToolResult(False, "", reason, 1, [], 0)
    try:
        return ToolResult(True, path.read_text(encoding="utf-8-sig"), "", 0, [str(path)], 0)
    except Exception as exc:
        return ToolResult(False, "", str(exc), 1, [], 0)


def write_file(path: Path, content: str, policy: PermissionPolicy) -> ToolResult:
    ok, reason = policy.validate_path(path)
    if not ok:
        return ToolResult(False, "", reason, 1, [], 0)
    try:
        before = path.read_text(encoding="utf-8-sig") if path.exists() and path.is_file() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        diff = _diff_text(before, content, path)
        history_id = _record_patch_history(path, before, content, "write", policy)
        stdout = f"wrote {path.name}"
        if history_id:
            stdout += f"\npatch_id={history_id}"
        if diff:
            stdout += f"\n{diff}"
        return ToolResult(True, stdout, "", 0, [str(path)], 0)
    except Exception as exc:
        return ToolResult(False, "", str(exc), 1, [], 0)


def patch_file(path: Path, find: str, replace: str, policy: PermissionPolicy, count: int = 1) -> ToolResult:
    ok, reason = policy.validate_path(path)
    if not ok:
        return ToolResult(False, "", reason, 1, [], 0)
    try:
        if not path.exists() or not path.is_file():
            return ToolResult(False, "", f"File not found: {path.name}", 1, [], 0)
        before = path.read_text(encoding="utf-8-sig")
        if find not in before:
            return ToolResult(False, "", "Target snippet not found.", 1, [], 0)
        after = before.replace(find, replace, count)
        path.write_text(after, encoding="utf-8")
        diff = _diff_text(before, after, path)
        history_id = _record_patch_history(path, before, after, "patch", policy)
        stdout = f"patched {path.name}"
        if history_id:
            stdout += f"\npatch_id={history_id}"
        if diff:
            stdout += f"\n{diff}"
        return ToolResult(True, stdout, "", 0, [str(path)], 0)
    except Exception as exc:
        return ToolResult(False, "", str(exc), 1, [], 0)


def delete_file(path: Path, policy: PermissionPolicy) -> ToolResult:
    ok, reason = policy.validate_path(path)
    if not ok:
        return ToolResult(False, "", reason, 1, [], 0)
    try:
        if not path.exists() or not path.is_file():
            return ToolResult(False, "", f"File not found: {path.name}", 1, [], 0)
        before = path.read_text(encoding="utf-8-sig")
        _record_patch_history(path, before, "", "delete", policy)
        path.unlink()
        stdout = f"deleted {path.name}"
        return ToolResult(True, stdout, "", 0, [str(path)], 0)
    except Exception as exc:
        return ToolResult(False, "", str(exc), 1, [], 0)


def search_code(repo_path: Path, needle: str, limit: int = 20) -> ToolResult:
    matches: list[str] = []
    lowered = needle.lower()
    for p in _iter_repo_files(repo_path):
        if p.suffix.lower() in TEXT_SKIP_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        if lowered in text.lower():
            matches.append(str(p.relative_to(repo_path).as_posix()))
            if len(matches) >= limit:
                break
    return ToolResult(True, "\n".join(matches), "", 0, matches, 0)


def list_files(repo_path: Path, pattern: str = "*", limit: int = 200) -> ToolResult:
    matches: list[str] = []
    for p in _iter_repo_files(repo_path, pattern=pattern):
        matches.append(str(p.relative_to(repo_path).as_posix()))
        if len(matches) >= limit:
            break
    return ToolResult(True, "\n".join(matches), "", 0, matches, 0)
