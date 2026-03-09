from pathlib import Path
import shutil

from agent_os.memory.store import MemoryStore


def test_memory_store_persists_chat_history() -> None:
    base = Path("tests/.tmp_memory_store").resolve()
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    store = MemoryStore(base / "agent_os.db")

    store.append_chat_message(chat_id="chat-1", role="assistant", content="hello", status="ready", executor="assistant")
    store.append_chat_message(
        chat_id="chat-1",
        role="user",
        content="fix the dashboard",
        task_id="task-1",
        status="queued",
        executor="collab_agent",
        logs=["planner started"],
        artifacts=[{"tool": "read_file", "artifacts": ["README.md"], "stdout": "text"}],
    )

    chats = store.list_chats(limit=5)
    assert chats
    assert chats[0]["chat_id"] == "chat-1"
    assert chats[0]["message_count"] == 2

    messages = store.messages_for_chat("chat-1")
    assert len(messages) == 2
    assert messages[1]["task_id"] == "task-1"
    assert messages[1]["logs"] == ["planner started"]
    assert messages[1]["artifacts"][0]["tool"] == "read_file"

    shutil.rmtree(base, ignore_errors=True)
