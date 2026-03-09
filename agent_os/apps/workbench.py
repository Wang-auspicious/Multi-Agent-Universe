from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, jsonify, request

from agent_os.core.runtime import AgentRuntime
from agent_os.memory.store import MemoryStore
from agent_os.tools.permissions import PermissionPolicy
from agent_os.tools.files import (
    IGNORED_DIRS,
    IGNORED_PREFIXES,
    TEXT_SKIP_SUFFIXES,
    patch_file,
    patch_history,
    read_file,
    rollback_patch,
    write_file,
)


REFERENCE_ARCHIVES = {"codex-main", "gemini-cli-main", "void-main", "vscode-main", "openclaw-main"}
EXECUTORS = ("collab_agent", "local_agent", "shell", "codex_cli", "gemini_cli", "claude_cli")
MAX_FILE_LIST = 2200
STATIC_DIR = Path(__file__).with_name("workbench_static")
INDEX_PATH = STATIC_DIR / "index.html"


def format_timestamp(value: str) -> str:
    if not value:
        return ""
    candidate = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return value
    return dt.strftime("%m-%d %H:%M:%S")


def trim_text(value: str, limit: int = 96) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def iter_workspace_files(repo_path: Path, include_archives: bool = False, limit: int = MAX_FILE_LIST) -> list[str]:
    repo_path = repo_path.resolve()
    rows: list[str] = []
    for root, dirs, files in os.walk(repo_path):
        current = Path(root)
        rel_root = current.relative_to(repo_path) if current != repo_path else Path()
        parts = rel_root.parts
        dirs[:] = [
            name
            for name in dirs
            if name not in IGNORED_DIRS
            and not any(name.startswith(prefix) for prefix in IGNORED_PREFIXES)
            and (include_archives or (not parts and name not in REFERENCE_ARCHIVES))
        ]
        if parts and any(part in IGNORED_DIRS for part in parts):
            continue
        if parts and any(any(part.startswith(prefix) for prefix in IGNORED_PREFIXES) for part in parts):
            continue
        if parts and not include_archives and parts[0] in REFERENCE_ARCHIVES:
            continue
        for name in sorted(files):
            if len(rows) >= limit:
                return rows
            path = current / name
            rel = path.relative_to(repo_path)
            if path.suffix.lower() in TEXT_SKIP_SUFFIXES:
                continue
            rows.append(rel.as_posix())
    return rows


def build_file_tree(paths: list[str]) -> list[dict[str, object]]:
    root: dict[str, dict[str, object]] = {}
    for path in paths:
        parts = path.split("/")
        cursor = root
        for index, part in enumerate(parts):
            full_path = "/".join(parts[: index + 1])
            is_file = index == len(parts) - 1
            node = cursor.setdefault(
                part,
                {
                    "name": part,
                    "path": full_path,
                    "type": "file" if is_file else "dir",
                    "children": {},
                },
            )
            if not is_file:
                node["type"] = "dir"
                cursor = node["children"]  # type: ignore[assignment]

    def _serialize(nodes: dict[str, dict[str, object]]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for _, node in sorted(nodes.items(), key=lambda item: (item[1]["type"] == "file", item[0].lower())):
            record = {"name": node["name"], "path": node["path"], "type": node["type"]}
            if node["type"] == "dir":
                record["children"] = _serialize(node["children"])  # type: ignore[index]
            rows.append(record)
        return rows

    return _serialize(root)


def build_buffer_diff(path: Path, before: str, after: str) -> str:
    if before == after:
        return f"No changes for {path.name}."
    import difflib

    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
        lineterm="",
    )
    return "\n".join(lines)


def extract_artifact_diff(artifact: dict[str, object]) -> str:
    content = ""
    if artifact.get("content"):
        try:
            decoded = json.loads(str(artifact["content"]))
        except Exception:
            decoded = {}
        if isinstance(decoded, dict):
            content = str(decoded.get("stdout", ""))
    if not content:
        content = str(artifact.get("stdout", ""))
    diff_lines = [line for line in content.splitlines() if line.startswith(("---", "+++", "@@", "+", "-"))]
    return "\n".join(diff_lines)


def git_snapshot(repo_path: Path) -> dict[str, object]:
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo_path, capture_output=True, text=True, check=False)
        status = subprocess.run(["git", "status", "--short"], cwd=repo_path, capture_output=True, text=True, check=False)
    except Exception:
        return {"branch": "detached", "modified": []}
    modified = [line for line in status.stdout.splitlines() if line.strip()]
    return {"branch": branch.stdout.strip() or "detached", "modified": modified}


def load_run_summary(repo_path: Path, task_id: str) -> str:
    summary_path = repo_path / "data" / "runs" / task_id / "summary.md"
    if not summary_path.exists():
        return ""
    return summary_path.read_text(encoding="utf-8")


def load_run_artifacts(repo_path: Path, task_id: str) -> list[dict[str, object]]:
    artifacts_path = repo_path / "data" / "runs" / task_id / "artifacts.json"
    if not artifacts_path.exists():
        return []
    try:
        payload = json.loads(artifacts_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def fetch_task_row(store, task_id: str) -> dict[str, object] | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT task_id, goal, status, summary, cost_tokens, cost_usd, assigned_executor, created_at, updated_at FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None

def create_app(repo_path: Path) -> Flask:
    repo_path = repo_path.resolve()
    runtime_ref: dict[str, AgentRuntime | None] = {"value": None}
    store = MemoryStore(repo_path / "data" / "agent_os.db")
    policy = PermissionPolicy(repo_path=repo_path)
    live_tasks: dict[str, dict[str, object]] = {}
    live_lock = threading.Lock()

    def get_runtime() -> AgentRuntime:
        if runtime_ref["value"] is None:
            runtime_ref["value"] = AgentRuntime(repo_path)
        return runtime_ref["value"]

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

    def _task_payload(task_id: str) -> dict[str, object]:
        with live_lock:
            live = dict(live_tasks.get(task_id, {}))
        return {
            "task": fetch_task_row(store, task_id),
            "summary": load_run_summary(repo_path, task_id),
            "artifacts": load_run_artifacts(repo_path, task_id),
            "events": store.events_for_task(task_id),
            "checkpoint": store.get_task_checkpoint(task_id),
            "live": live,
        }

    def _chat_payload(chat_id: str) -> dict[str, object]:
        return {
            "chat": store.get_chat(chat_id),
            "messages": store.messages_for_chat(chat_id),
        }

    def _bootstrap() -> dict[str, object]:
        default_health = {name: (name in {"collab_agent", "local_agent", "shell"}) for name in EXECUTORS}
        return {
            "repo_path": str(repo_path),
            "repo_name": repo_path.name,
            "executors": [{"name": name, "ok": bool(default_health.get(name, False))} for name in EXECUTORS],
            "git": git_snapshot(repo_path),
            "tasks": store.recent_tasks(limit=36),
            "chats": store.list_chats(limit=24),
        }

    def _checkpoint_logs(task_id: str) -> list[str]:
        events = store.events_for_task(task_id)
        return [
            f"{format_timestamp(str(event.get('created_at', '')))}  {event.get('event_type', '')}  {trim_text(json.dumps(event.get('payload', {}), ensure_ascii=False), 120)}"
            for event in events
        ]

    def _run_task_worker(task_id: str, chat_id: str, goal: str, executor: str, conversation: list[dict[str, str]]) -> None:
        def _update_live(**kwargs: object) -> None:
            with live_lock:
                state = live_tasks.setdefault(task_id, {"running": True, "chat_id": chat_id, "executor": executor})
                state.update(kwargs)

        try:
            result = get_runtime().run_task(
                goal=goal,
                constraints=[],
                on_event=lambda event: _update_live(running=True, last_event=event.event_type, updated_at=event.created_at),
                executor_override=executor,
                fallback_to_shell=True,
                conversation_history=conversation,
                task_id=task_id,
            )
        except Exception as exc:
            error_text = f"Task failed: {exc}"
            store.append_chat_message(chat_id=chat_id, role="assistant", content=error_text, task_id=task_id, status="error", executor=executor)
            checkpoint = store.get_task_checkpoint(task_id) or {}
            store.upsert_task_checkpoint(
                task_id=task_id,
                chat_id=chat_id,
                goal=str(checkpoint.get("goal", goal)),
                executor=executor,
                status="error",
                conversation=list(checkpoint.get("conversation", [])) + [{"role": "assistant", "content": error_text}],
                logs=_checkpoint_logs(task_id),
                summary=error_text,
                created_at=str(checkpoint.get("created_at", "")) or None,
            )
            _update_live(running=False, error=str(exc), status="error")
            return

        store.append_chat_message(
            chat_id=chat_id,
            role="assistant",
            content=result.summary,
            task_id=task_id,
            status=result.status,
            executor=result.executor,
            artifacts=result.artifacts,
        )
        checkpoint = store.get_task_checkpoint(task_id) or {}
        store.upsert_task_checkpoint(
            task_id=task_id,
            chat_id=chat_id,
            goal=str(checkpoint.get("goal", goal)),
            executor=result.executor,
            status=result.status,
            conversation=list(checkpoint.get("conversation", [])) + [{"role": "assistant", "content": result.summary}],
            logs=_checkpoint_logs(task_id),
            summary=result.summary,
            created_at=str(checkpoint.get("created_at", "")) or None,
        )
        _update_live(running=False, status=result.status, summary=result.summary)

    @app.get("/")
    def index() -> Response:
        return Response(INDEX_PATH.read_text(encoding="utf-8"), mimetype="text/html")

    @app.get("/api/bootstrap")
    def bootstrap() -> Response:
        return jsonify(_bootstrap())

    @app.get("/api/explorer")
    def explorer() -> Response:
        include_archives = request.args.get("include_archives", "0") == "1"
        query = request.args.get("q", "").strip().lower()
        files = iter_workspace_files(repo_path, include_archives=include_archives, limit=MAX_FILE_LIST)
        if query:
            files = [item for item in files if query in item.lower()]
        return jsonify({"count": len(files), "tree": build_file_tree(files)})

    @app.get("/api/file")
    def file_detail() -> Response:
        path = request.args.get("path", "").strip()
        result = read_file(repo_path / path, policy)
        return jsonify(
            {
                "ok": result.ok,
                "path": path,
                "content": result.stdout if result.ok else "",
                "error": result.stderr if not result.ok else "",
                "history": patch_history(repo_path / path, policy, limit=24),
            }
        )

    @app.post("/api/file/diff")
    def file_diff() -> Response:
        payload = request.get_json(force=True) or {}
        path = Path(str(payload.get("path", "buffer")))
        before = str(payload.get("before", ""))
        after = str(payload.get("after", ""))
        return jsonify({"diff": build_buffer_diff(path, before, after)})

    @app.post("/api/file/save")
    def file_save() -> Response:
        payload = request.get_json(force=True) or {}
        path = str(payload.get("path", "")).strip()
        content = str(payload.get("content", ""))
        result = write_file(repo_path / path, content, policy)
        return jsonify({
            "ok": result.ok,
            "error": result.stderr,
            "content": content if result.ok else "",
            "history": patch_history(repo_path / path, policy, limit=24),
        })

    @app.post("/api/file/patch")
    def file_patch() -> Response:
        payload = request.get_json(force=True) or {}
        path = str(payload.get("path", "")).strip()
        find = str(payload.get("find", ""))
        replace = str(payload.get("replace", ""))
        count = int(payload.get("count", 1) or 1)
        result = patch_file(repo_path / path, find, replace, policy, count=count)
        current = read_file(repo_path / path, policy)
        return jsonify({
            "ok": result.ok,
            "error": result.stderr,
            "content": current.stdout if current.ok else "",
            "history": patch_history(repo_path / path, policy, limit=24),
        })

    @app.get("/api/file/history")
    def file_history() -> Response:
        path = request.args.get("path", "").strip()
        return jsonify({"history": patch_history(repo_path / path, policy, limit=24)})

    @app.post("/api/file/rollback")
    def file_rollback() -> Response:
        payload = request.get_json(force=True) or {}
        path = str(payload.get("path", "")).strip()
        entry_id = str(payload.get("entry_id", "")).strip() or None
        result = rollback_patch(repo_path / path, policy, entry_id=entry_id)
        current = read_file(repo_path / path, policy)
        return jsonify({
            "ok": result.ok,
            "error": result.stderr,
            "content": current.stdout if current.ok else "",
            "history": patch_history(repo_path / path, policy, limit=24),
        })

    @app.get("/api/chats")
    def chats() -> Response:
        return jsonify({"chats": store.list_chats(limit=24)})

    @app.get("/api/chat/<chat_id>")
    def chat_detail(chat_id: str) -> Response:
        return jsonify(_chat_payload(chat_id))

    @app.get("/api/tasks")
    def tasks() -> Response:
        return jsonify({"tasks": store.recent_tasks(limit=36)})

    @app.get("/api/task/<task_id>")
    def task_detail(task_id: str) -> Response:
        return jsonify(_task_payload(task_id))

    @app.post("/api/task/run")
    def task_run() -> Response:
        payload = request.get_json(force=True) or {}
        goal = str(payload.get("goal", "")).strip()
        executor = str(payload.get("executor", "collab_agent")).strip() or "collab_agent"
        chat_id = str(payload.get("chat_id", "")).strip() or uuid4().hex[:10]
        if not goal:
            return jsonify({"ok": False, "error": "Goal is required."}), 400

        task_id = uuid4().hex[:12]
        messages = store.messages_for_chat(chat_id)
        conversation = [{"role": str(row["role"]), "content": str(row["content"])} for row in messages if str(row["role"]) in {"user", "assistant"}]
        store.append_chat_message(chat_id=chat_id, role="user", content=goal, task_id=task_id, status="queued", executor=executor)
        store.upsert_task_checkpoint(
            task_id=task_id,
            chat_id=chat_id,
            goal=goal,
            executor=executor,
            status="queued",
            conversation=conversation + [{"role": "user", "content": goal}],
            logs=[],
            summary="",
        )
        with live_lock:
            live_tasks[task_id] = {"running": True, "chat_id": chat_id, "executor": executor, "status": "queued"}
        worker = threading.Thread(target=_run_task_worker, args=(task_id, chat_id, goal, executor, conversation), daemon=True)
        worker.start()
        return jsonify({"ok": True, "task_id": task_id, "chat_id": chat_id})

    return app


def pick_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local web workbench for Agent Universe")
    parser.add_argument("--repo", default=".", help="Repository root path")
    parser.add_argument("--port", type=int, default=0, help="Port to bind")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    port = args.port or pick_port()
    app = create_app(repo_path)
    url = f"http://127.0.0.1:{port}"
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Agent Universe Workbench running at {url}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()







