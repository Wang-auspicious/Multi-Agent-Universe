from __future__ import annotations

import json
from dataclasses import dataclass

from agent_os.core.workspace import CollaborationBoard, WorkItem
from agent_os.providers.base import ProviderBase


@dataclass
class PlanResult:
    summary: str
    items: list[WorkItem]


class PlannerAgent:
    def __init__(self, provider: ProviderBase) -> None:
        self.provider = provider

    def _extract_json(self, text: str) -> dict[str, object] | None:
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{") and part.endswith("}"):
                    try:
                        return json.loads(part)
                    except Exception:
                        pass
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                return None
        return None

    def _looks_like_capability_question(self, goal: str) -> bool:
        tokens = ("你能做什么", "可以做什么", "高级任务", "有哪些能力", "what can you do")
        return any(token in goal.lower() or token in goal for token in tokens)

    def _heuristic_plan(self, goal: str, constraints: list[str]) -> PlanResult:
        lowered = goal.lower()
        items: list[WorkItem] = []

        if self._looks_like_capability_question(goal):
            items.append(WorkItem(title="Summarize collaboration capabilities", owner="writer", goal=goal, kind="explanation"))
            items.append(WorkItem(title="Review capability summary", owner="reviewer", goal=goal, kind="review"))
            return PlanResult(summary="Capability question routed to writer-first lightweight flow.", items=items)

        if any(token in lowered for token in ("readme", ".md", "文档", "说明", "写文", "文本", "呈现", "原样")):
            items.append(WorkItem(title="Inspect relevant files", owner="coder", goal=f"Inspect the repository files needed for: {goal}", kind="analysis"))
            items.append(WorkItem(title="Prepare user-facing wording", owner="writer", goal=goal, kind="documentation"))
        elif any(token in lowered for token in ("实现", "修复", "重构", "代码", "功能", "bug", "test", "测试", "接口", "模块", "模板")):
            items.append(WorkItem(title="Inspect codebase context", owner="coder", goal=f"Inspect the repository and find the relevant code for: {goal}", kind="analysis"))
            items.append(WorkItem(title="Implement code changes", owner="coder", goal=goal, kind="implementation"))
            items.append(WorkItem(title="Write supporting docs", owner="writer", goal=f"Write a concise developer-facing summary for: {goal}", kind="documentation"))
        else:
            items.append(WorkItem(title="Inspect repository context", owner="coder", goal=goal, kind="analysis"))
            items.append(WorkItem(title="Prepare final answer", owner="writer", goal=goal, kind="documentation"))

        items.append(WorkItem(title="Review outputs", owner="reviewer", goal=f"Review the work produced for: {goal}", kind="review"))
        return PlanResult(summary="Heuristic multi-agent plan generated.", items=items)

    def plan(self, goal: str, constraints: list[str] | None = None, conversation_history: list[dict[str, str]] | None = None) -> PlanResult:
        constraints = constraints or []
        conversation_history = conversation_history or []
        if self._looks_like_capability_question(goal):
            return self._heuristic_plan(goal, constraints)

        prompt = (
            "Break the repository task into a small multi-agent plan. Return JSON only.\n"
            "Use owners only from: planner, coder, writer, reviewer.\n"
            "Keep 2-4 items. Reviewer should usually be last.\n"
            "Avoid unnecessary analysis items for simple questions.\n"
            "Use recent conversation history to resolve references like this file or that change.\n"
            "JSON schema:\n"
            '{"summary":"short summary","items":[{"title":"...","owner":"coder","goal":"...","kind":"analysis|implementation|documentation|review|explanation"}]}\n\n'
            f"Goal: {goal}\nConstraints: {constraints}"
            f"\nRecent conversation: {json.dumps(conversation_history[-8:], ensure_ascii=False)}"
        )
        resp = self.provider.generate(prompt, system="You are a planning agent for a collaborative coding workflow. Return JSON only.")
        payload = self._extract_json(resp.text)
        if not payload:
            return self._heuristic_plan(goal, constraints)

        items_payload = payload.get("items", [])
        if not isinstance(items_payload, list) or not items_payload:
            return self._heuristic_plan(goal, constraints)

        items: list[WorkItem] = []
        for raw in items_payload[:4]:
            if not isinstance(raw, dict):
                continue
            owner = str(raw.get("owner", "coder")).strip().lower()
            if owner not in {"planner", "coder", "writer", "reviewer"}:
                owner = "coder"
            items.append(
                WorkItem(
                    title=str(raw.get("title", "Untitled task")).strip() or "Untitled task",
                    owner=owner,
                    goal=str(raw.get("goal", goal)).strip() or goal,
                    kind=str(raw.get("kind", "analysis")).strip() or "analysis",
                )
            )
        if not items:
            return self._heuristic_plan(goal, constraints)
        return PlanResult(summary=str(payload.get("summary", "Multi-agent plan generated.")).strip() or "Multi-agent plan generated.", items=items)

    def initialize_board(
        self,
        task_id: str,
        goal: str,
        constraints: list[str] | None = None,
        repo_overview: dict[str, object] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> CollaborationBoard:
        plan = self.plan(goal, constraints, conversation_history=conversation_history)
        board = CollaborationBoard(
            task_id=task_id,
            goal=goal,
            constraints=constraints or [],
            plan_summary=plan.summary,
            repo_overview=repo_overview or {},
            conversation_history=conversation_history or [],
        )
        for item in plan.items:
            board.add_item(item)
        board.add_note("planner", plan.summary)
        return board
