from agent_os.agents.router import RouterAgent


def test_router_defaults_to_collab_agent() -> None:
    route = RouterAgent().decide('fix bug in auth')
    assert route.target_agent == 'planner'
    assert route.executor == 'collab_agent'


def test_router_routes_review_through_collab_agent() -> None:
    route = RouterAgent().decide('review this diff and risks')
    assert route.target_agent == 'planner'
    assert route.executor == 'collab_agent'


def test_router_detects_codex_executor() -> None:
    route = RouterAgent().decide('use codex cli to fix this')
    assert route.executor == 'codex_cli'
