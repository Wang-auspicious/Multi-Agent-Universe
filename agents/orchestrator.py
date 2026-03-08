from __future__ import annotations

from typing import Callable

from agents import search_agent, analysis_agent
from agents.agent_log import LogEntry, log
from agents.cost_tracker import CostTracker, get

_SEARCH_TRIGGERS: tuple[str, ...] = ("搜索", "查询", "找", "查一下", "帮我查")


def run(
    user_input: str,
    tracker: CostTracker | None = None,
    log_cb: Callable[[LogEntry], None] | None = None,
) -> tuple[str, CostTracker]:
    """主调度入口，返回 (最终结果, CostTracker)"""
    if tracker is None:
        tracker = get()  # CLI 模式使用全局 tracker

    log("Orchestrator", f"接收指令: {user_input}", log_cb)

    # 意图识别：是否触发搜索流水线
    if any(kw in user_input for kw in _SEARCH_TRIGGERS):
        log("Orchestrator", "意图识别 → 搜索+分析流水线", log_cb)

        # Step 1: Search Agent
        results = search_agent.run(user_input, tracker=tracker, log_cb=log_cb)

        # Step 2: Analysis Agent
        analysis = analysis_agent.run(user_input, results, tracker=tracker, log_cb=log_cb)

        log("Orchestrator", f"流水线完成 | 累计花费 ${tracker.used:.4f}", log_cb)
        return analysis, tracker

    # 非搜索意图：直接返回空，由 main.py 交给 Gemini 对话
    log("Orchestrator", "意图识别 → 普通对话，转交 Gemini", log_cb)
    return "", tracker
