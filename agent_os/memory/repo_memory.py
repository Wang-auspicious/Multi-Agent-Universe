from agent_os.memory.store import MemoryStore


class RepoMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def remember(self, key: str, value: str) -> None:
        self.store.set_repo_memory(key, value)
