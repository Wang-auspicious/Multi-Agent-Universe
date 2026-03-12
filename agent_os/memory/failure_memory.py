from agent_os.core.error_classifier import classify_error, ErrorClassification
from agent_os.memory.store import MemoryStore


class FailureMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def add(self, task_id: str, failure: str, fix_attempt: str, status: str, error_type: str | None = None, retry_count: int = 0) -> None:
        # Auto-classify if error_type not provided
        if error_type is None:
            classification = classify_error(failure)
            error_type = classification.error_type
        self.store.add_failure(task_id, failure, fix_attempt, status, error_type, retry_count)

    def classify_failure(self, failure_text: str) -> ErrorClassification:
        """Classify a failure and return classification details."""
        return classify_error(failure_text)
