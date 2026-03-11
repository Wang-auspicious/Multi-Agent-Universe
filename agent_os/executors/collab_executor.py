from __future__ import annotations

import json
from pathlib import Path

from agent_os.agents.planner import PlannerAgent
from agent_os.agents.writer import WriterAgent
from agent_os.core.graph import CollaborationState, ensure_graph_transition
from agent_os.core.workspace import CollaborationBoard, WorkItem
from agent_os.executors.base import ExecutorBase, ExecutorResult
from agent_os.providers.base import ProviderBase
from agent_os.tools.files import list_files, patch_file, patch_history, read_file, rollback_patch, search_code, write_file
from agent_os.tools.permissions import PermissionPolicy
from agent_os.tools.shell import SafeShell, ToolResult


class CollaborativeExecutor(ExecutorBase):
    name = "collab_agent"

    def __init__(
        self,
        repo_path: Path,
        planner_provider: ProviderBase,
        worker_provider: ProviderBase,
        shell: SafeShell,
        policy: PermissionPolicy,
        reviewer_provider: ProviderBase | None = None,
        final_provider: ProviderBase | None = None,
        max_steps: int = 4,
        max_repairs: int = 1,
    ) -> None:
        self.repo_path = repo_path
        self.planner_provider = planner_provider
        self.worker_provider = worker_provider
        self.reviewer_provider = reviewer_provider or planner_provider
        self.final_provider = final_provider or self.reviewer_provider
        self.shell = shell
        self.policy = policy
        self.max_steps = max_steps
        self.max_repairs = max_repairs
        self.planner = PlannerAgent(self.planner_provider)
        self.writer = WriterAgent(self.worker_provider)
        self._artifacts: list[dict[str, object]] = []
        self._context: dict[str, object] = {}

    def prepare(self, context: dict[str, object]) -> None:
        self._artifacts.clear()
        self._context = dict(context)

    def healthcheck(self) -> bool:
        return bool(self.planner_provider.is_available() and self.worker_provider.is_available())

    def _append_artifact(self, payload: dict[str, object]) -> None:
        self._artifacts.append(payload)

    def _repo_overview(self) -> dict[str, object]:
        top_entries = []
        for path in sorted(self.repo_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if path.name.startswith('.') and path.name not in {'.env', '.gitignore'}:
                continue
            if path.name.startswith('pytest-cache-files-'):
                continue
            top_entries.append({"name": path.name, "type": "dir" if path.is_dir() else "file"})
            if len(top_entries) >= 24:
                break
        key_files = [item["name"] for item in top_entries if item["type"] == "file"][:10]
        return {"top_entries": top_entries, "key_files": key_files}

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
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None

    def _normalize_args(self, args: dict[str, object]) -> dict[str, object]:
        normalized = dict(args)
        if "path" not in normalized:
            for alias in ("file_path", "filepath", "filename"):
                if alias in normalized:
                    normalized["path"] = normalized[alias]
                    break
        if "query" not in normalized and "needle" in normalized:
            normalized["query"] = normalized["needle"]
        if "content" not in normalized and "text" in normalized:
            normalized["content"] = normalized["text"]
        if "find" not in normalized and "old" in normalized:
            normalized["find"] = normalized["old"]
        if "replace" not in normalized and "new" in normalized:
            normalized["replace"] = normalized["new"]
        return normalized

    def _simple_tool_result(self, stdout: str, path: str = "") -> ToolResult:
        artifacts = [str(self.repo_path / path)] if path else []
        return ToolResult(True, stdout, "", 0, artifacts, 0)

    def _tool_result(self, role: str, item_id: str, name: str, result: ToolResult) -> dict[str, object]:
        artifact = {
            "kind": "tool_result",
            "role": role,
            "item_id": item_id,
            "tool": name,
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "artifacts": result.artifacts,
            "duration_ms": result.duration_ms,
        }
        self._append_artifact(artifact)
        return artifact

    def _run_tool(self, role: str, item_id: str, action: dict[str, object]) -> dict[str, object]:
        tool = str(action.get("tool", ""))
        args = action.get("args", {})
        if not isinstance(args, dict):
            args = {}
        args = self._normalize_args(args)

        if tool == "list_files":
            return self._tool_result(role, item_id, tool, list_files(self.repo_path, pattern=str(args.get("pattern", "*")), limit=int(args.get("limit", 80))))
        if tool == "read_file":
            return self._tool_result(role, item_id, tool, read_file(self.repo_path / str(args.get("path", "")), self.policy))
        if tool in {"write_file", "write_to_file"}:
            return self._tool_result(role, item_id, "write_file", write_file(self.repo_path / str(args.get("path", "")), str(args.get("content", "")), self.policy))
        if tool in {"apply_patch", "patch_file"}:
            return self._tool_result(role, item_id, "apply_patch", patch_file(self.repo_path / str(args.get("path", "")), str(args.get("find", "")), str(args.get("replace", "")), self.policy, count=int(args.get("count", 1))))
        if tool == "patch_history":
            rows = patch_history(self.repo_path / str(args.get("path", "")), self.policy, limit=int(args.get("limit", 20)))
            return self._tool_result(role, item_id, tool, self._simple_tool_result(json.dumps(rows, ensure_ascii=False, indent=2), str(args.get("path", ""))))
        if tool == "rollback_patch":
            return self._tool_result(role, item_id, tool, rollback_patch(self.repo_path / str(args.get("path", "")), self.policy, entry_id=str(args.get("entry_id", "")).strip() or None))
        if tool == "search_code":
            return self._tool_result(role, item_id, tool, search_code(self.repo_path, needle=str(args.get("query", "")), limit=int(args.get("limit", 12))))
        if tool == "run_command":
            return self._tool_result(role, item_id, tool, self.shell.run(str(args.get("command", "")), timeout_s=int(args.get("timeout_s", 60))))

        artifact = {
            "kind": "tool_result",
            "role": role,
            "item_id": item_id,
            "tool": tool,
            "ok": False,
            "stdout": "",
            "stderr": f"unknown tool: {tool}",
            "exit_code": 1,
            "artifacts": [],
            "duration_ms": 0,
        }
        self._append_artifact(artifact)
        return artifact

    def _provider_for_role(self, role: str) -> ProviderBase:
        if role == "planner":
            return self.planner_provider
        if role == "reviewer":
            return self.reviewer_provider
        return self.worker_provider

    def _role_system_prompt(self, role: str) -> str:
        if role == "writer":
            return self.writer.system_prompt() + " Use write_file or apply_patch when the user explicitly asks to create or edit docs."
        if role == "reviewer":
            return (
                "You are the Reviewer agent in a collaborative coding workflow. "
                "Review completed work items and verify claims against completed artifacts only. "
                "Return JSON only with fields approved, answer, and optional repair_goal."
            )
        return (
            "You are the Coder agent in a collaborative coding workflow. "
            "Use tools to inspect and modify the repository. "
            "Prefer repo_overview before exploration. "
            "Use recent conversation history to resolve references such as this file or the previous change. "
            "For file edits, prefer apply_patch for targeted changes and write_file for new files or full rewrites. "
            "When writing a file, use args.path and args.content. When patching, use args.path, args.find, args.replace. "
            "Use patch_history and rollback_patch when the user asks about reverting edits. "
            "If the user asks to see a file's text, return the exact text instead of summarizing it. "
            "Return JSON only."
        )

    def _build_role_prompt(self, board: CollaborationBoard, item: WorkItem, history: list[dict[str, object]]) -> str:
        ready_items = [ready.as_dict() for ready in board.ready_items() if ready.item_id != item.item_id]
        inbox = board.inbox_for(item.owner)
        return (
            f"Board context:\n{json.dumps(board.as_context(), ensure_ascii=False, indent=2)}\n\n"
            f"Current work item:\n{json.dumps(item.as_dict(), ensure_ascii=False, indent=2)}\n\n"
            f"Current tool history:\n{json.dumps(history, ensure_ascii=False, indent=2)}\n\n"
            f"Ready teammate work items:\n{json.dumps(ready_items, ensure_ascii=False, indent=2)}\n\n"
            f"Mailbox for this role:\n{json.dumps(inbox, ensure_ascii=False, indent=2)}\n\n"
            "You are part of a shared agent team. The planner is the team lead.\n"
            "You must return JSON only.\n"
            "Do not repeat exploration if repo_overview, notes, mailbox, or prior history already answers it.\n"
            "Do not claim files were updated unless a write_file/apply_patch/rollback_patch tool result succeeded in this task.\n"
            "If you discover something another teammate needs, you may send a mailbox message.\n"
            "Tool schemas:\n"
            "- read_file: {\"path\": \"relative/path\"}\n"
            "- write_file: {\"path\": \"relative/path\", \"content\": \"...\"}\n"
            "- apply_patch: {\"path\": \"relative/path\", \"find\": \"old snippet\", \"replace\": \"new snippet\", \"count\": 1}\n"
            "- patch_history: {\"path\": \"relative/path\", \"limit\": 20}\n"
            "- rollback_patch: {\"path\": \"relative/path\", \"entry_id\": \"optional patch id\"}\n"
            "- search_code: {\"query\": \"text\", \"limit\": 12}\n"
            "- run_command: {\"command\": \"pytest -q\", \"timeout_s\": 60}\n"
            "If you need a tool, return {\"mode\":\"tool\",\"tool\":\"tool_name\",\"args\":{...},\"reason\":\"short\"}.\n"
            "If you need to update another teammate, return {\"mode\":\"message\",\"recipient\":\"planner|coder|writer|reviewer|all\",\"content\":\"short note\"}.\n"
            "If the work item is complete, return {\"mode\":\"final\",\"answer\":\"direct answer for this work item\",\"message\":\"optional note to planner\"}.\n"
        )

    def _artifact_diff_blocks(self) -> list[dict[str, object]]:
        blocks: list[dict[str, object]] = []
        for artifact in self._successful_artifacts():
            if artifact.get("tool") not in {"write_file", "apply_patch", "rollback_patch"}:
                continue
            stdout = str(artifact.get("stdout", ""))
            diff_lines = [line for line in stdout.splitlines() if line.startswith(("---", "+++", "@@", "+", "-"))]
            if not diff_lines:
                continue
            path = ((artifact.get("artifacts") or [""]) or [""])[0]
            blocks.append({"path": path, "diff": "\n".join(diff_lines[:200])})
        return blocks

    def _git_diff_snapshot(self) -> str:
        result = self.shell.run("git diff --no-ext-diff --relative", timeout_s=30)
        if result.ok and result.stdout:
            return result.stdout[:12000]
        return ""

    def _run_role_loop(self, board: CollaborationBoard, item: WorkItem) -> tuple[bool, str, list[dict[str, object]]]:
        history: list[dict[str, object]] = []
        role = item.owner
        final_answer = ""
        ok = True
        provider = self._provider_for_role(role)
        board.claim_item(item.item_id, role)
        board.send_message("planner", role, f"You own work item: {item.title}", item.item_id)

        for _ in range(self.max_steps):
            prompt = self._build_role_prompt(board, item, history)
            resp = provider.generate(prompt, system=self._role_system_prompt(role))
            payload = self._extract_json(resp.text)
            if not payload:
                final_answer = resp.text.strip() or "No valid role output."
                ok = False
                break

            if payload.get("mode") == "message":
                recipient = str(payload.get("recipient", "planner")).strip() or "planner"
                content = str(payload.get("content", "")).strip()
                if content:
                    board.send_message(role, recipient, content, item.item_id)
                    self._append_artifact({
                        "kind": "mailbox_message",
                        "role": role,
                        "item_id": item.item_id,
                        "recipient": recipient,
                        "content": content,
                    })
                continue

            if payload.get("mode") == "final":
                final_answer = str(payload.get("answer", "")).strip()
                lead_message = str(payload.get("message", "")).strip()
                if lead_message:
                    board.send_message(role, "planner", lead_message, item.item_id)
                    self._append_artifact({
                        "kind": "mailbox_message",
                        "role": role,
                        "item_id": item.item_id,
                        "recipient": "planner",
                        "content": lead_message,
                    })
                break

            if payload.get("mode") == "tool":
                result = self._run_tool(role, item.item_id, payload)
                history.append({"action": payload, "result": result})
                ok = ok and bool(result.get("ok", False))
                continue

            final_answer = "Role returned unsupported mode."
            ok = False
            break

        if not final_answer and history:
            last = history[-1]["result"]
            final_answer = str(last.get("stdout") or last.get("stderr") or "Work item finished.")

        board.send_message(role, "planner", final_answer[:400], item.item_id)
        return ok, final_answer or "Work item finished.", history

    def _review_json(self, board: CollaborationBoard, item: WorkItem) -> dict[str, object]:
        completed = [
            {"title": work.title, "owner": work.owner, "goal": work.goal, "result": work.result}
            for work in board.completed_items()
            if work.item_id != item.item_id
        ]
        verified_artifacts = [artifact for artifact in self._artifacts if artifact.get("tool") in {"write_file", "apply_patch", "rollback_patch", "patch_history", "run_command", "read_file", "search_code"}]
        diff_blocks = self._artifact_diff_blocks()
        git_diff = self._git_diff_snapshot()
        prompt = (
            "Review the completed collaborative work. Return JSON only.\n"
            "Check scope fit, correctness, missing coverage, risky edits, and whether the answer matches the actual diffs.\n"
            '{"approved": true, "answer": "...", "repair_goal": "... optional ...", "findings": ["..."]}\n\n'
            f"User goal: {board.goal}\n"
            f"Recent conversation: {json.dumps(board.conversation_history[-8:], ensure_ascii=False, indent=2)}\n"
            f"Completed work: {json.dumps(completed, ensure_ascii=False, indent=2)}\n"
            f"Mailbox: {json.dumps(board.as_context().get('mailbox', []), ensure_ascii=False, indent=2)}\n"
            f"Verified artifacts: {json.dumps(verified_artifacts, ensure_ascii=False, indent=2)}\n"
            f"Artifact diffs: {json.dumps(diff_blocks, ensure_ascii=False, indent=2)}\n"
            f"Git diff snapshot:\n{git_diff or '(empty)'}"
        )
        resp = self.reviewer_provider.generate(prompt, system=self._role_system_prompt("reviewer"))
        payload = self._extract_json(resp.text)
        if payload:
            return payload
        return {"approved": True, "answer": (resp.text or "Review complete.").strip(), "repair_goal": ""}

    def _run_reviewer(self, board: CollaborationBoard, item: WorkItem) -> tuple[bool, str, str]:
        payload = self._review_json(board, item)
        approved = bool(payload.get("approved", True))
        answer = str(payload.get("answer", "Review complete.")).strip() or "Review complete."
        repair_goal = str(payload.get("repair_goal", "")).strip()
        return approved, answer, repair_goal

    def _successful_artifacts(self) -> list[dict[str, object]]:
        return [artifact for artifact in self._artifacts if artifact.get("kind") == "tool_result" and artifact.get("ok")]

    def _exact_readback_if_requested(self, goal: str) -> str | None:
        lowered = goal.lower()
        wants_exact = any(token in goal for token in ("原样", "呈现", "完整", "文字是什么", "内容是什么")) or "exact" in lowered
        if not wants_exact:
            return None
        read_results = [artifact for artifact in self._successful_artifacts() if artifact.get("tool") == "read_file" and artifact.get("stdout")]
        if not read_results:
            return None
        latest = read_results[-1]
        path = (latest.get("artifacts") or [""])[0]
        return f"{Path(path).name} 的内容如下：\n\n{latest.get('stdout', '')}"

    def _verified_summary(self, board: CollaborationBoard, review_answer: str) -> str:
        exact = self._exact_readback_if_requested(board.goal)
        if exact:
            return exact

        writes = [artifact for artifact in self._successful_artifacts() if artifact.get("tool") == "write_file"]
        patches = [artifact for artifact in self._successful_artifacts() if artifact.get("tool") in {"apply_patch", "rollback_patch"}]
        commands = [artifact for artifact in self._successful_artifacts() if artifact.get("tool") == "run_command"]
        reads = [artifact for artifact in self._successful_artifacts() if artifact.get("tool") == "read_file"]

        facts = {
            "goal": board.goal,
            "recent_conversation": board.conversation_history[-8:],
            "plan_summary": board.plan_summary,
            "writes": [{"path": (a.get("artifacts") or [""])[0], "stdout": a.get("stdout", "")} for a in writes],
            "patches": [{"path": (a.get("artifacts") or [""])[0], "stdout": a.get("stdout", "")} for a in patches],
            "commands": [{"stdout": a.get("stdout", ""), "stderr": a.get("stderr", "")} for a in commands],
            "reads": [{"path": (a.get("artifacts") or [""])[0]} for a in reads],
            "review": review_answer,
            "completed_items": [
                {"owner": item.owner, "title": item.title, "status": item.status, "result": item.result}
                for item in board.completed_items()
            ],
        }
        prompt = (
            "Write the final user-facing answer in concise Chinese using only the verified facts below.\n"
            "Do not invent file changes.\n"
            "If files were created or modified, name them explicitly.\n\n"
            f"Verified facts: {json.dumps(facts, ensure_ascii=False, indent=2)}"
        )
        resp = self.final_provider.generate(prompt, system="You are a factual finalizer. Use only verified artifacts.")
        if resp.model != "offline-fallback" and resp.text.strip():
            return resp.text.strip()

        lines = []
        if writes:
            file_names = ", ".join(Path((a.get("artifacts") or [""])[0]).name for a in writes if a.get("artifacts"))
            lines.append(f"已创建或重写文件：{file_names}。")
        if patches:
            file_names = ", ".join(Path((a.get("artifacts") or [""])[0]).name for a in patches if a.get("artifacts"))
            lines.append(f"已通过补丁修改文件：{file_names}。")
        if commands:
            lines.append("已执行相关命令并获得结果。")
        if not lines:
            lines.append("任务已完成。")
        lines.append(f"审查结论：{review_answer}")
        return "\n".join(lines)

    def _execute_non_review_items(self, board: CollaborationBoard) -> bool:
        ok = True
        while True:
            ready = board.ready_items()
            if not ready:
                break
            item = ready[0]
            item.status = "running"
            self._append_artifact({
                "kind": "work_item_started",
                "role": item.owner,
                "item_id": item.item_id,
                "title": item.title,
                "goal": item.goal,
                "depends_on": list(item.depends_on),
            })
            item_ok, result_text, history = self._run_role_loop(board, item)
            item.status = "done" if item_ok else "blocked"
            item.result = result_text
            item.artifacts = history
            ok = ok and item_ok
            board.add_note(item.owner, result_text[:1200])
            self._append_artifact({
                "kind": "work_item_completed",
                "role": item.owner,
                "item_id": item.item_id,
                "title": item.title,
                "status": item.status,
                "result": result_text,
            })
        return ok

    def run(self, task_id: str, goal: str, constraints: list[str] | None = None) -> ExecutorResult:
        if not self.healthcheck():
            return ExecutorResult(ok=False, summary=f"collab_agent unavailable: planner={self.planner_provider.last_error or 'n/a'} worker={self.worker_provider.last_error or 'n/a'}", artifacts=[], executor=self.name)

        state = CollaborationState.PLAN
        board = self.planner.initialize_board(
            task_id=task_id,
            goal=goal,
            constraints=constraints,
            repo_overview=self._repo_overview(),
            conversation_history=list(self._context.get("conversation_history", [])) if isinstance(self._context.get("conversation_history", []), list) else [],
        )
        self._append_artifact({
            "kind": "plan",
            "role": "planner",
            "state": state.value,
            "summary": board.plan_summary,
            "plan_status": board.plan_status,
            "items": [item.as_dict() for item in board.items],
            "repo_overview": board.repo_overview,
            "mailbox": board.as_context().get("mailbox", []),
        })

        repair_count = 0
        overall_ok = True
        reviewer_answer = "Approved"
        reviewer_item = next((item for item in board.items if item.owner == "reviewer"), None)

        ensure_graph_transition(state, CollaborationState.EXECUTE)
        state = CollaborationState.EXECUTE
        overall_ok = self._execute_non_review_items(board) and overall_ok

        while True:
            ensure_graph_transition(state, CollaborationState.REVIEW)
            state = CollaborationState.REVIEW
            if reviewer_item is None:
                reviewer_item = WorkItem(title="Review outputs", owner="reviewer", goal=f"Review outputs for: {goal}", kind="review")
                board.add_item(reviewer_item)
            reviewer_item.status = "running"
            self._append_artifact({
                "kind": "work_item_started",
                "role": "reviewer",
                "item_id": reviewer_item.item_id,
                "title": reviewer_item.title,
                "goal": reviewer_item.goal,
            })
            approved, reviewer_answer, repair_goal = self._run_reviewer(board, reviewer_item)
            reviewer_item.status = "done" if approved else "blocked"
            reviewer_item.result = reviewer_answer
            board.add_note("reviewer", reviewer_answer[:1200])
            board.send_message("reviewer", "planner", reviewer_answer[:400], reviewer_item.item_id)
            self._append_artifact({
                "kind": "work_item_completed",
                "role": "reviewer",
                "item_id": reviewer_item.item_id,
                "title": reviewer_item.title,
                "status": reviewer_item.status,
                "result": reviewer_answer,
            })
            if approved or repair_count >= self.max_repairs:
                overall_ok = overall_ok and approved
                break

            ensure_graph_transition(state, CollaborationState.REPAIR)
            state = CollaborationState.REPAIR
            repair_count += 1
            repair_item = WorkItem(
                title=f"Address review findings #{repair_count}",
                owner="coder",
                goal=repair_goal or f"Address reviewer feedback: {reviewer_answer}",
                kind="repair",
                depends_on=[reviewer_item.item_id],
                priority=1,
            )
            board.add_item(repair_item)
            overall_ok = self._execute_non_review_items(board) and overall_ok

        ensure_graph_transition(state, CollaborationState.FINALIZE)
        state = CollaborationState.FINALIZE
        final_answer = self._verified_summary(board, reviewer_answer)
        self._append_artifact({
            "kind": "board_finalized",
            "role": "planner",
            "state": state.value,
            "summary": final_answer,
            "board": board.as_context(),
        })
        ensure_graph_transition(state, CollaborationState.DONE)
        return ExecutorResult(ok=overall_ok, summary=final_answer, artifacts=self._artifacts, executor=self.name)

    def get_artifacts(self) -> list[dict[str, object]]:
        return list(self._artifacts)






