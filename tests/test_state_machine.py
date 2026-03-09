from agent_os.core.models import TaskStatus
from agent_os.core.state_machine import InvalidTransitionError, ensure_transition


def test_valid_transition() -> None:
    ensure_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)


def test_invalid_transition_raises() -> None:
    raised = False
    try:
        ensure_transition(TaskStatus.QUEUED, TaskStatus.DONE)
    except InvalidTransitionError:
        raised = True
    assert raised
