from agent_os.memory.store import MemoryStore


class FailureMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def add(self, task_id: str, failure: str, fix_attempt: str, status: str) -> None:
        self.store.add_failure(task_id, failure, fix_attempt, status)
