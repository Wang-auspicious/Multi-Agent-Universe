from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_os.agents import CoderAgent, ReviewerAgent, RouterAgent, SummarizerAgent
from agent_os.core.bus import EventBus
from agent_os.core.events import Event, EventTypes
from agent_os.core.models import Artifact, Task, TaskStatus
from agent_os.core.state_machine import ensure_transition
from agent_os.executors import ClaudeExecutor, CodexExecutor, GeminiCliExecutor, LocalAgentExecutor, ShellExecutor
from agent_os.executors.collab_executor import CollaborativeExecutor
from agent_os.memory import FailureMemory, MemoryStore, RepoMemory, TaskMemory
from agent_os.providers.factory import get_provider
from agent_os.tools.permissions import PermissionPolicy
from agent_os.tools.shell import SafeShell


@dataclass
class RunResult:
    task_id: str
    status: str
    summary: str
    review_feedback: str
    artifacts_count: int
    tokens: int
    cost_usd: float
    executor: str
    artifacts: list[dict[str, object]]


class AgentRuntime:
    def __init__(self, repo_path: Path, retry_limit: int = 1) -> None:
        self.repo_path = repo_path.resolve()
        self.data_dir = self.repo_path / "data"
        self.runs_dir = self.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        self.bus = EventBus()
        self.store = MemoryStore(self.data_dir / "agent_os.db")
        self.repo_memory = RepoMemory(self.store)
        self.task_memory = TaskMemory(self.store)
        self.failure_memory = FailureMemory(self.store)

        self.policy = PermissionPolicy(repo_path=self.repo_path)
        self.shell = SafeShell(repo_path=self.repo_path, policy=self.policy)
        self.fast_provider = get_provider("sub2api_fast")
        self.strong_provider = get_provider("sub2api_strong")
        self.final_provider = get_provider("sub2api_final")

        planner_provider = self.strong_provider if self.strong_provider.is_available() else self.fast_provider
        reviewer_provider = planner_provider
        final_provider = self.final_provider if self.final_provider.is_available() else planner_provider

        collab = CollaborativeExecutor(
            repo_path=self.repo_path,
            planner_provider=planner_provider,
            worker_provider=self.fast_provider,
            reviewer_provider=reviewer_provider,
            final_provider=final_provider,
            shell=self.shell,
            policy=self.policy,
        )
        self.executors = {
            "collab_agent": collab,
            "local_agent": collab,
            "shell": ShellExecutor(repo_path=self.repo_path, shell=self.shell),
            "codex_cli": CodexExecutor(repo_path=self.repo_path),
            "gemini_cli": GeminiCliExecutor(repo_path=self.repo_path),
            "claude_cli": ClaudeExecutor(repo_path=self.repo_path),
        }

        self.router = RouterAgent()
        self.coder = CoderAgent()
        self.reviewer = ReviewerAgent()
        self.summarizer = SummarizerAgent(provider=final_provider)

        self._event_hook: Callable[[Event], None] | None = None
        self.retry_limit = max(0, retry_limit)

    def _emit(self, event_type: str, task: Task, payload: dict[str, object]) -> None:
        event = Event(event_type=event_type, task_id=task.task_id, payload=payload)
        self.bus.publish(event)
        self.store.append_event(task.task_id, event.event_type, event.payload, event.created_at)
        if self._event_hook:
            self._event_hook(event)

    def _attach_run_logger(self, task: Task) -> Path:
        run_dir = self.runs_dir / task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.jsonl"

        def _write(event: Event) -> None:
            with events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

        self.bus.subscribe(_write)
        return run_dir

    def _estimate_cost(self, tokens: int) -> float:
        return tokens * ((3.0 + 15.0) / 2) / 1_000_000

    def executor_health(self) -> dict[str, bool]:
        rows: dict[str, bool] = {}
        for name, executor in self.executors.items():
            try:
                rows[name] = bool(executor.healthcheck())
            except Exception:
                rows[name] = False
        return rows

    def _emit_artifact_events(self, task: Task, item: dict[str, object]) -> None:
        kind = str(item.get("kind", ""))
        if kind == "plan":
            self._emit(EventTypes.PLAN_CREATED, task, {"summary": item.get("summary", ""), "items": item.get("items", []), "state": item.get("state", "plan")})
            return
        if kind == "work_item_started":
            self._emit(EventTypes.WORK_ITEM_STARTED, task, item)
            return
        if kind == "work_item_completed":
            self._emit(EventTypes.WORK_ITEM_COMPLETED, task, item)
            return
        if kind == "board_finalized":
            self._emit(EventTypes.WORKSPACE_UPDATED, task, {"summary": item.get("summary", ""), "state": item.get("state", "finalize")})
            return

        command_name = item.get("command") or item.get("tool") or ""
        if command_name:
            self._emit(EventTypes.COMMAND_STARTED, task, {"command": command_name})
            self._emit(EventTypes.COMMAND_FINISHED, task, item)

    def _run_coder_once(self, task: Task, executor_name: str, goal: str) -> dict[str, object]:
        executor = self.executors.get(executor_name) or self.executors["collab_agent"]
        self._emit(EventTypes.AGENT_STARTED, task, {"agent": "coder", "executor": executor.name})
        coder_output = self.coder.run(
            executor,
            task.task_id,
            goal,
            task.constraints,
            extra_context={"conversation_history": task.conversation_history},
        )
        artifacts = coder_output.get("artifacts", [])
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            self._emit_artifact_events(task, item)
            task.artifacts.append(Artifact(kind=str(item.get("kind", "command_result")), content=json.dumps(item, ensure_ascii=False)))
        if artifacts:
            self._emit(EventTypes.DIFF_GENERATED, task, {"artifacts": len(artifacts), "executor": executor.name})
        return coder_output

    def _derive_direct_answer(self, goal: str, coder_output: dict[str, object]) -> str | None:
        lowered = goal.lower()
        if ".py" in lowered and ("how many" in lowered or "count" in lowered or "统计" in goal or "多少" in goal):
            text = str(coder_output.get("summary", ""))
            nums = re.findall(r"\b\d+\b", text)
            if nums:
                return f"Direct answer: there are currently {nums[-1]} .py files."
        return None

    def run_task(
        self,
        goal: str,
        constraints: list[str] | None = None,
        on_event: Callable[[Event], None] | None = None,
        executor_override: str | None = None,
        fallback_to_shell: bool = True,
        conversation_history: list[dict[str, str]] | None = None,
        task_id: str | None = None,
        chat_id: str | None = None,
    ) -> RunResult:
        task = Task(
            repo_path=self.repo_path,
            goal=goal,
            constraints=constraints or [],
            conversation_history=conversation_history or [],
            task_id=task_id or Task(repo_path=self.repo_path, goal=goal).task_id,
        )
        run_dir = self._attach_run_logger(task)
        self._event_hook = on_event

        try:
            self._emit(EventTypes.TASK_CREATED, task, {"goal": goal})

            # Save initial checkpoint with chat_id
            if chat_id:
                self.store.upsert_task_checkpoint(
                    task_id=task.task_id,
                    chat_id=chat_id,
                    goal=goal,
                    executor=executor_override or "collab_agent",
                    status="pending",
                    conversation=conversation_history or [],
                    logs=[],
                )

            ensure_transition(task.status, TaskStatus.RUNNING)
            task.status = TaskStatus.RUNNING
            task.touch()
            self.store.upsert_task(
                task_id=task.task_id,
                goal=task.goal,
                status=task.status.value,
                summary="",
                cost_tokens=0,
                created_at=task.created_at,
                updated_at=task.updated_at,
                cost_usd=0.0,
                assigned_executor="",
            )

            # Update checkpoint to in_progress
            if chat_id:
                self.store.upsert_task_checkpoint(
                    task_id=task.task_id,
                    chat_id=chat_id,
                    goal=goal,
                    executor=executor_override or "collab_agent",
                    status="in_progress",
                    conversation=conversation_history or [],
                    logs=[],
                )

            route = self.router.decide(goal)
            requested_executor = executor_override or route.executor
            selected_executor = requested_executor
            if fallback_to_shell and requested_executor not in {"shell", "local_agent", "collab_agent"}:
                ex = self.executors.get(requested_executor)
                if ex is None or not ex.healthcheck():
                    selected_executor = "collab_agent"

            task.assigned_executor = selected_executor
            task.touch()
            self.store.upsert_task(
                task_id=task.task_id,
                goal=task.goal,
                status=task.status.value,
                summary=task.summary,
                cost_tokens=task.cost_tokens,
                created_at=task.created_at,
                updated_at=task.updated_at,
                cost_usd=0.0,
                assigned_executor=selected_executor,
            )
            self._emit(
                EventTypes.TASK_ASSIGNED,
                task,
                {
                    "target_agent": route.target_agent,
                    "executor": selected_executor,
                    "requested_executor": requested_executor,
                    "reason": route.reason,
                    "override": bool(executor_override),
                    "fallback_to_shell": selected_executor != requested_executor,
                },
            )

            coder_output = self._run_coder_once(task, selected_executor, goal)

            ensure_transition(task.status, TaskStatus.REVIEW)
            task.status = TaskStatus.REVIEW
            task.touch()
            self.store.upsert_task(
                task_id=task.task_id,
                goal=task.goal,
                status=task.status.value,
                summary=task.summary,
                cost_tokens=task.cost_tokens,
                created_at=task.created_at,
                updated_at=task.updated_at,
                cost_usd=0.0,
                assigned_executor=selected_executor,
            )

            self._emit(EventTypes.AGENT_STARTED, task, {"agent": "reviewer"})
            review = self.reviewer.review(coder_output)

            if not review["approved"]:
                self._emit(EventTypes.REVIEW_FAILED, task, review)
                self.failure_memory.add(task.task_id, str(review["feedback"]), "review failed", "open")
                ensure_transition(task.status, TaskStatus.BLOCKED)
                task.status = TaskStatus.BLOCKED
                task.touch()

            self._emit(EventTypes.AGENT_STARTED, task, {"agent": "summarizer"})
            summary, tokens = self.summarizer.summarize(task.goal, coder_output, review)
            direct = self._derive_direct_answer(goal, coder_output)
            if direct and direct not in summary:
                summary = f"{direct}\n\n{summary}"
            cost_usd = self._estimate_cost(tokens)

            if task.status != TaskStatus.BLOCKED:
                ensure_transition(task.status, TaskStatus.DONE)
                task.status = TaskStatus.DONE

            task.summary = summary
            task.cost_tokens = tokens
            task.touch()

            self.store.upsert_task(
                task_id=task.task_id,
                goal=task.goal,
                status=task.status.value,
                summary=task.summary,
                cost_tokens=task.cost_tokens,
                created_at=task.created_at,
                updated_at=task.updated_at,
                cost_usd=cost_usd,
                assigned_executor=selected_executor,
            )

            artifacts_path = run_dir / "artifacts.json"
            artifacts_payload = [asdict(a) for a in task.artifacts]
            artifacts_path.write_text(json.dumps(artifacts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")

            self.repo_memory.remember("last_goal", task.goal)
            self._emit(
                EventTypes.TASK_COMPLETED,
                task,
                {"status": task.status.value, "tokens": task.cost_tokens, "cost_usd": cost_usd, "executor": selected_executor},
            )

            # Update checkpoint to completed
            if chat_id:
                self.store.upsert_task_checkpoint(
                    task_id=task.task_id,
                    chat_id=chat_id,
                    goal=goal,
                    executor=selected_executor,
                    status="completed",
                    summary=summary,
                    conversation=conversation_history or [],
                    logs=[],
                )

            return RunResult(
                task_id=task.task_id,
                status=task.status.value,
                summary=task.summary,
                review_feedback=str(review.get("feedback", "")),
                artifacts_count=len(task.artifacts),
                tokens=task.cost_tokens,
                cost_usd=cost_usd,
                executor=selected_executor,
                artifacts=coder_output.get("artifacts", []),
            )
        finally:
            self._event_hook = None

