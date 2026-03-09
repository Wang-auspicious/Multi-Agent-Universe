from agent_os.core.graph import CollaborationState, InvalidGraphTransition, ensure_graph_transition


def test_valid_collaboration_transitions() -> None:
    ensure_graph_transition(CollaborationState.PLAN, CollaborationState.EXECUTE)
    ensure_graph_transition(CollaborationState.EXECUTE, CollaborationState.REVIEW)
    ensure_graph_transition(CollaborationState.REVIEW, CollaborationState.REPAIR)
    ensure_graph_transition(CollaborationState.REPAIR, CollaborationState.REVIEW)
    ensure_graph_transition(CollaborationState.REVIEW, CollaborationState.FINALIZE)
    ensure_graph_transition(CollaborationState.FINALIZE, CollaborationState.DONE)


def test_invalid_collaboration_transition_raises() -> None:
    try:
        ensure_graph_transition(CollaborationState.PLAN, CollaborationState.REVIEW)
    except InvalidGraphTransition:
        return
    raise AssertionError("expected InvalidGraphTransition")
