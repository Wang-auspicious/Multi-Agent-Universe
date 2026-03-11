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
        lowered = goal.lower()
        tokens = ("你能做什么", "可以做什么", "高级任务", "有哪些能力", "what can you do")
        return any(token in lowered or token in goal for token in tokens)

    def _heuristic_plan(self, goal: str, constraints: list[str]) -> PlanResult:
        lowered = goal.lower()
        items: list[WorkItem] = []

        if self._looks_like_capability_question(goal):
            explain = WorkItem(title="Summarize collaboration capabilities", owner="writer", goal=goal, kind="explanation", priority=2)
            review = WorkItem(title="Review capability summary", owner="reviewer", goal=goal, kind="review", depends_on=[explain.item_id], priority=4)
            items.extend([explain, review])
            return PlanResult(summary="Capability question routed to writer-first lightweight flow.", items=items)

        inspect = WorkItem(title="Inspect repository context", owner="coder", goal=f"Inspect the relevant repository context for: {goal}", kind="analysis", priority=1)
        items.append(inspect)

        if any(token in lowered for token in ("readme", ".md", "文档", "说明", "写文", "文本", "呈现", "原样")):
            draft = WorkItem(title="Draft developer-facing response", owner="writer", goal=goal, kind="documentation", depends_on=[inspect.item_id], priority=2)
            items.append(draft)
        elif any(token in lowered for token in ("实现", "修复", "重构", "代码", "功能", "bug", "test", "测试", "接口", "模块", "模板")):
            implement = WorkItem(title="Implement repository changes", owner="coder", goal=goal, kind="implementation", depends_on=[inspect.item_id], priority=1)
            explain = WorkItem(title="Write concise implementation notes", owner="writer", goal=f"Summarize the implemented changes for: {goal}", kind="documentation", depends_on=[implement.item_id], priority=3)
            items.extend([implement, explain])
        else:
            answer = WorkItem(title="Prepare final answer", owner="writer", goal=goal, kind="documentation", depends_on=[inspect.item_id], priority=2)
            items.append(answer)

        review_dep = items[-1].item_id if items else inspect.item_id
        review = WorkItem(title="Review outputs", owner="reviewer", goal=f"Review the work produced for: {goal}", kind="review", depends_on=[review_dep], priority=4)
        items.append(review)
        return PlanResult(summary="Heuristic multi-agent plan generated.", items=items)

    def plan(self, goal: str, constraints: list[str] | None = None, conversation_history: list[dict[str, str]] | None = None) -> PlanResult:
        constraints = constraints or []
        conversation_history = conversation_history or []
        if self._looks_like_capability_question(goal):
            return self._heuristic_plan(goal, constraints)

        prompt = (
            "Break the repository task into a small multi-agent team plan. Return JSON only.\n"
            "Use owners only from: planner, coder, writer, reviewer.\n"
            "Keep 2-5 items. Reviewer should usually be last.\n"
            "Each item may depend on earlier items by title.\n"
            "The planner acts as team lead and should prefer explicit dependencies over vague ordering.\n"
            "Use recent conversation history to resolve references like this file or that change.\n"
            "JSON schema:\n"
            '{"summary":"short summary","items":[{"title":"...","owner":"coder","goal":"...","kind":"analysis|implementation|documentation|review|explanation","depends_on":["Earlier title"],"priority":1}]}\n\n'
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
        title_to_id: dict[str, str] = {}
        for raw in items_payload[:5]:
            if not isinstance(raw, dict):
                continue
            owner = str(raw.get("owner", "coder")).strip().lower()
            if owner not in {"planner", "coder", "writer", "reviewer"}:
                owner = "coder"
            item = WorkItem(
                title=str(raw.get("title", "Untitled task")).strip() or "Untitled task",
                owner=owner,
                goal=str(raw.get("goal", goal)).strip() or goal,
                kind=str(raw.get("kind", "analysis")).strip() or "analysis",
                priority=int(raw.get("priority", 3) or 3),
            )
            depends_titles = raw.get("depends_on", [])
            if isinstance(depends_titles, list):
                item.depends_on = [title_to_id[name] for name in depends_titles if isinstance(name, str) and name in title_to_id]
            items.append(item)
            title_to_id[item.title] = item.item_id
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
        board.send_message("planner", "all", f"Plan ready: {plan.summary}")
        board.approve_plan()
        return board
