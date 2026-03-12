from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _safe_add_column(self, conn: sqlite3.Connection, sql: str) -> None:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT,
                    cost_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    assigned_executor TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS repo_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS failure_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    failure TEXT NOT NULL,
                    fix_attempt TEXT,
                    status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chats (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    task_id TEXT DEFAULT '',
                    status TEXT DEFAULT '',
                    executor TEXT DEFAULT '',
                    logs_json TEXT DEFAULT '[]',
                    artifacts_json TEXT DEFAULT '[]',
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    task_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    executor TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    resumed_from TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    conversation_json TEXT DEFAULT '[]',
                    logs_json TEXT DEFAULT '[]',
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id, id);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id, id);
                CREATE INDEX IF NOT EXISTS idx_task_checkpoints_status ON task_checkpoints(status, updated_at);
                """
            )
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "cost_usd" not in cols:
                self._safe_add_column(conn, "ALTER TABLE tasks ADD COLUMN cost_usd REAL DEFAULT 0")
            if "assigned_executor" not in cols:
                self._safe_add_column(conn, "ALTER TABLE tasks ADD COLUMN assigned_executor TEXT DEFAULT ''")

    def upsert_task(
        self,
        task_id: str,
        goal: str,
        status: str,
        summary: str,
        cost_tokens: int,
        created_at: str,
        updated_at: str,
        cost_usd: float = 0.0,
        assigned_executor: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(task_id, goal, status, summary, cost_tokens, cost_usd, assigned_executor, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    summary=excluded.summary,
                    cost_tokens=excluded.cost_tokens,
                    cost_usd=excluded.cost_usd,
                    assigned_executor=excluded.assigned_executor,
                    updated_at=excluded.updated_at
                """,
                (task_id, goal, status, summary, cost_tokens, cost_usd, assigned_executor, created_at, updated_at),
            )

    def upsert_task_checkpoint(
        self,
        task_id: str,
        chat_id: str,
        goal: str,
        executor: str,
        status: str,
        conversation: list[dict[str, Any]] | None = None,
        logs: list[str] | None = None,
        resumed_from: str = "",
        summary: str = "",
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        created = created_at or _utc_now()
        updated = updated_at or created
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_checkpoints(
                    task_id, chat_id, goal, executor, status, resumed_from, summary, conversation_json, logs_json, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    chat_id=excluded.chat_id,
                    goal=excluded.goal,
                    executor=excluded.executor,
                    status=excluded.status,
                    resumed_from=excluded.resumed_from,
                    summary=excluded.summary,
                    conversation_json=excluded.conversation_json,
                    logs_json=excluded.logs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    chat_id,
                    goal,
                    executor,
                    status,
                    resumed_from,
                    summary,
                    json.dumps(conversation or [], ensure_ascii=False),
                    json.dumps(logs or [], ensure_ascii=False),
                    created,
                    updated,
                ),
            )

    def get_task_checkpoint(self, task_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    task_id, chat_id, goal, executor, status, resumed_from, summary,
                    conversation_json, logs_json, created_at, updated_at
                FROM task_checkpoints
                WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "chat_id": row["chat_id"],
            "goal": row["goal"],
            "executor": row["executor"],
            "status": row["status"],
            "resumed_from": row["resumed_from"],
            "summary": row["summary"],
            "conversation": json.loads(row["conversation_json"] or "[]"),
            "logs": json.loads(row["logs_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_task_checkpoints(self, limit: int = 20, statuses: list[str] | None = None) -> list[dict[str, object]]:
        sql = """
            SELECT
                task_id, chat_id, goal, executor, status, resumed_from, summary,
                conversation_json, logs_json, created_at, updated_at
            FROM task_checkpoints
        """
        params: tuple[Any, ...] = ()
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" WHERE status IN ({placeholders})"
            params = tuple(statuses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "chat_id": row["chat_id"],
                "goal": row["goal"],
                "executor": row["executor"],
                "status": row["status"],
                "resumed_from": row["resumed_from"],
                "summary": row["summary"],
                "conversation": json.loads(row["conversation_json"] or "[]"),
                "logs": json.loads(row["logs_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def append_event(self, task_id: str, event_type: str, payload: dict[str, object], created_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events(task_id, event_type, payload_json, created_at) VALUES(?,?,?,?)",
                (task_id, event_type, json.dumps(payload, ensure_ascii=False), created_at),
            )

    def set_repo_memory(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO repo_memory(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, value),
            )

    def add_failure(self, task_id: str, failure: str, fix_attempt: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO failure_memory(task_id, failure, fix_attempt, status) VALUES(?,?,?,?)",
                (task_id, failure, fix_attempt, status),
            )

    def recent_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, goal, status, summary, cost_tokens, cost_usd, assigned_executor, created_at, updated_at
                FROM tasks
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def events_for_task(self, task_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, payload_json, created_at FROM events WHERE task_id=? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def upsert_chat(self, chat_id: str, title: str, created_at: str | None = None, updated_at: str | None = None) -> None:
        created = created_at or _utc_now()
        updated = updated_at or created
        safe_title = (title or "New chat").strip() or "New chat"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats(chat_id, title, created_at, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=CASE
                        WHEN chats.title IS NULL OR chats.title = '' OR chats.title = 'New chat' THEN excluded.title
                        ELSE chats.title
                    END,
                    updated_at=excluded.updated_at
                """,
                (chat_id, safe_title, created, updated),
            )

    def rename_chat(self, chat_id: str, title: str) -> None:
        safe_title = (title or "New chat").strip() or "New chat"
        with self._connect() as conn:
            conn.execute(
                "UPDATE chats SET title=?, updated_at=? WHERE chat_id=?",
                (safe_title, _utc_now(), chat_id),
            )

    def get_chat(self, chat_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chat_id, title, created_at, updated_at FROM chats WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def append_chat_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        task_id: str = "",
        status: str = "",
        executor: str = "",
        logs: list[str] | None = None,
        artifacts: list[dict[str, object]] | None = None,
        created_at: str | None = None,
    ) -> None:
        timestamp = created_at or _utc_now()
        self.upsert_chat(chat_id, title=self._infer_chat_title(chat_id, content), updated_at=timestamp)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages(chat_id, role, content, task_id, status, executor, logs_json, artifacts_json, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    chat_id,
                    role,
                    content,
                    task_id,
                    status,
                    executor,
                    json.dumps(logs or [], ensure_ascii=False),
                    json.dumps(artifacts or [], ensure_ascii=False),
                    timestamp,
                ),
            )
            conn.execute("UPDATE chats SET updated_at=? WHERE chat_id=?", (timestamp, chat_id))

    def _infer_chat_title(self, chat_id: str, content: str) -> str:
        current = self.get_chat(chat_id)
        if current and str(current.get("title", "")).strip() not in {"", "New chat"}:
            return str(current["title"])
        clean = " ".join(content.split()).strip()
        return (clean[:56] + "...") if len(clean) > 56 else (clean or "New chat")

    def get_last_n_messages(self, chat_id: str, n: int = 10) -> list[dict[str, str]]:
        """Get last N messages in conversation history format for LLM context."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE chat_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, n),
            ).fetchall()
        messages = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
        return messages

    def messages_for_chat(self, chat_id: str, limit: int | None = None) -> list[dict[str, object]]:
        sql = """
            SELECT chat_id, role, content, task_id, status, executor, logs_json, artifacts_json, created_at
            FROM chat_messages
            WHERE chat_id=?
            ORDER BY id ASC
        """
        params: tuple[Any, ...] = (chat_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (chat_id, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "chat_id": row["chat_id"],
                "role": row["role"],
                "content": row["content"],
                "task_id": row["task_id"],
                "status": row["status"],
                "executor": row["executor"],
                "logs": json.loads(row["logs_json"] or "[]"),
                "artifacts": json.loads(row["artifacts_json"] or "[]"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_chats(self, limit: int = 24) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.chat_id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) AS message_count,
                    COALESCE((
                        SELECT content
                        FROM chat_messages last_msg
                        WHERE last_msg.chat_id = c.chat_id
                        ORDER BY last_msg.id DESC
                        LIMIT 1
                    ), '') AS last_message,
                    COALESCE((
                        SELECT role
                        FROM chat_messages last_msg
                        WHERE last_msg.chat_id = c.chat_id
                        ORDER BY last_msg.id DESC
                        LIMIT 1
                    ), '') AS last_role
                FROM chats c
                LEFT JOIN chat_messages m ON m.chat_id = c.chat_id
                GROUP BY c.chat_id, c.title, c.created_at, c.updated_at
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        chats = [dict(row) for row in rows]
        for chat in chats:
            preview = " ".join(str(chat.get("last_message", "")).split()).strip()
            chat["preview"] = (preview[:88] + "...") if len(preview) > 88 else preview
        return chats

    def recent_failures(self, limit: int = 10) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, failure, fix_attempt, status, created_at
                FROM failure_memory
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def dashboard_snapshot(self, task_limit: int = 8, chat_limit: int = 8) -> dict[str, object]:
        tasks = self.recent_tasks(limit=task_limit)
        chats = self.list_chats(limit=chat_limit)
        failures = self.recent_failures(limit=6)
        checkpoints = self.list_task_checkpoints(limit=6)
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM tasks) AS task_count,
                    (SELECT COUNT(*) FROM chats) AS chat_count,
                    (SELECT COUNT(*) FROM chat_messages) AS message_count,
                    (SELECT COUNT(*) FROM events) AS event_count,
                    (SELECT COUNT(*) FROM task_checkpoints) AS checkpoint_count
                """
            ).fetchone()
        return {
            "counts": dict(counts) if counts else {},
            "tasks": tasks,
            "chats": chats,
            "failures": failures,
            "checkpoints": checkpoints,
        }
