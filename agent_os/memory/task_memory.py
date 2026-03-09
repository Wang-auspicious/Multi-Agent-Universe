from agent_os.memory.store import MemoryStore


class TaskMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def list_recent(self, limit: int = 20) -> list[dict[str, object]]:
        return self.store.recent_tasks(limit)
