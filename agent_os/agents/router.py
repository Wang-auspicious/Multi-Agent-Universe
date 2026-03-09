from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteDecision:
    target_agent: str
    executor: str
    reason: str


class RouterAgent:
    def decide(self, goal: str) -> RouteDecision:
        lowered = goal.lower()

        if any(k in lowered for k in ("collab agent", "multi agent", "planner", "writer", "use collab")):
            return RouteDecision("planner", "collab_agent", "Task explicitly requests collaborative multi-agent execution")
        if any(k in lowered for k in ("local agent", "tool agent", "use local agent")):
            return RouteDecision("planner", "collab_agent", "Local agent tasks now run through collaborative executor")
        if any(k in lowered for k in ("codex", "use codex", "codex cli")):
            return RouteDecision("coder", "codex_cli", "Task explicitly requests Codex executor")
        if any(k in lowered for k in ("gemini cli", "use gemini", "gemini executor")):
            return RouteDecision("coder", "gemini_cli", "Task explicitly requests Gemini CLI executor")
        if any(k in lowered for k in ("claude cli", "use claude", "claude executor")):
            return RouteDecision("coder", "claude_cli", "Task explicitly requests Claude CLI executor")
        if any(k in lowered for k in ("shell", "命令行", "run command")):
            return RouteDecision("coder", "shell", "Task explicitly requests shell execution")
        return RouteDecision("planner", "collab_agent", "Default collaborative coding workflow path")
