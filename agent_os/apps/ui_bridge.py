from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_os.memory.store import MemoryStore


_STATE_MAP = {
    "task.created": ("researching", 5),
    "task.assigned": ("writing", 10),
    "plan.created": ("researching", 18),
    "work_item.started": ("executing", 40),
    "work_item.completed": ("syncing", 70),
    "workspace.updated": ("syncing", 88),
    "review.failed": ("error", 90),
    "task.completed": ("idle", 100),
}


def _payload_for_event(task_id: str, event_type: str, payload: dict[str, object]) -> dict[str, object]:
    state, progress = _STATE_MAP.get(event_type, ("executing", 55))
    if event_type == "plan.created":
        detail = f"Planner created {len(payload.get('items', []))} work items"
    elif event_type == "work_item.started":
        detail = f"{payload.get('role', 'agent')} started: {payload.get('title', '')}"
    elif event_type == "work_item.completed":
        detail = f"{payload.get('role', 'agent')} finished: {payload.get('title', '')}"
    else:
        detail = f"{event_type} | task={task_id}"
    return {
        "state": state,
        "detail": detail,
        "progress": progress,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def push_state(task_id: str, office_root: Path, repo_root: Path) -> Path:
    store = MemoryStore(repo_root / "data" / "agent_os.db")
    events = store.events_for_task(task_id)
    if not events:
        raise ValueError(f"No events found for task: {task_id}")

    latest = events[-1]
    payload = _payload_for_event(task_id, latest["event_type"], latest["payload"])
    target = office_root / "state.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def watch_task(task_id: str, office_root: Path, repo_root: Path, interval_s: float = 1.0) -> None:
    store = MemoryStore(repo_root / "data" / "agent_os.db")
    target = office_root / "state.json"
    seen = 0
    while True:
        events = store.events_for_task(task_id)
        if len(events) > seen:
            latest = events[-1]
            payload = _payload_for_event(task_id, latest["event_type"], latest["payload"])
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            seen = len(events)
            if latest["event_type"] == "task.completed":
                break
        time.sleep(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge Agent OS events to Star Office state.json")
    parser.add_argument("task_id")
    parser.add_argument("--office-root", default="Star-Office-UI-1.0.0")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    office_root = Path(args.office_root).resolve()
    repo_root = Path(args.repo).resolve()

    if args.watch:
        watch_task(task_id=args.task_id, office_root=office_root, repo_root=repo_root)
        print(f"Watched Star Office state for task: {args.task_id}")
        return

    written = push_state(task_id=args.task_id, office_root=office_root, repo_root=repo_root)
    print(f"Updated Star Office state: {written}")


if __name__ == "__main__":
    main()
