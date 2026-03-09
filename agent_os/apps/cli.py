from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_os.core.runtime import AgentRuntime

_EXECUTORS = ["collab_agent", "local_agent", "shell", "codex_cli", "gemini_cli", "claude_cli"]

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _should_quick_reply(prompt: str) -> bool:
    lowered = prompt.lower().strip()
    repo_tokens = ("file", "readme", "repo", "repository", "code", "git", "test", "create", "modify", "edit", "diff", "patch", ".py")
    if any(token in lowered for token in repo_tokens):
        return False
    return any(token in lowered for token in ("hello", "hi", "who are you", "what can you do")) or any(token in prompt for token in ("???", "??", "????", "?????"))


def _quick_reply(prompt: str) -> str:
    lowered = prompt.lower().strip()
    if "who are you" in lowered or "???" in prompt:
        return "I am the Agent OS collaborator for this repository. I can plan, edit files, review diffs, and summarize work inside the current workspace."
    if "what can you do" in lowered or any(token in prompt for token in ("????", "?????")):
        return "I can collaborate on repo tasks: inspect files, modify code, review diffs, write docs, and keep short multi-turn context inside the current chat."
    return "Hello. If you want me to work on the repo, tell me the file, code area, or task goal."


def _print_result(result) -> None:
    print(f"Task: {result.task_id}")
    print(f"Status: {result.status}")
    print(f"Executor: {result.executor}")
    print(f"Artifacts: {result.artifacts_count}")
    print(f"Tokens: {result.tokens}")
    print(f"Cost (est): ${result.cost_usd:.6f}")
    print("Summary:")
    print(result.summary)


def _choose_executor(runtime: AgentRuntime) -> str:
    health = runtime.executor_health()
    print("Choose executor:")
    for i, name in enumerate(_EXECUTORS, start=1):
        tag = "ok" if health.get(name, False) else "unavailable"
        print(f"{i}. {name} ({tag})")
    selected = input(f"Enter number [1-{len(_EXECUTORS)}] (default 1): ").strip()
    try:
        idx = int(selected) if selected else 1
    except ValueError:
        idx = 1
    idx = max(1, min(len(_EXECUTORS), idx))
    return _EXECUTORS[idx - 1]


def _chat_loop(runtime: AgentRuntime, executor: str, strict: bool) -> None:
    print(f"Chat mode started. executor={executor}, strict={strict}")
    print("Type 'exit' to quit.")
    conversation_history: list[dict[str, str]] = []
    while True:
        prompt = input("\nYou> ").strip()
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            break
        if _should_quick_reply(prompt):
            reply = _quick_reply(prompt)
            conversation_history.append({"role": "user", "content": prompt})
            conversation_history.append({"role": "assistant", "content": reply})
            print("\nAssistant>")
            print(reply)
            continue
        result = runtime.run_task(
            goal=prompt,
            constraints=[],
            executor_override=executor,
            fallback_to_shell=not strict,
            conversation_history=conversation_history,
        )
        conversation_history.append({"role": "user", "content": prompt})
        conversation_history.append({"role": "assistant", "content": result.summary})
        print("\nAssistant>")
        _print_result(result)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Collaborative coding workflow agent OS")
    parser.add_argument("goal", nargs="?", help="Natural language coding task")
    parser.add_argument("--repo", default=".", help="Repository root path")
    parser.add_argument("--constraint", action="append", default=[], help="Task constraint")
    parser.add_argument("--executor", choices=_EXECUTORS, help="Force executor")
    parser.add_argument("--retry", type=int, default=1, help="Reviewer retry limit")
    parser.add_argument("--healthcheck", action="store_true", help="Check executors availability and exit")
    parser.add_argument("--strict-executor", action="store_true", help="Do not fallback when selected executor is unavailable")
    parser.add_argument("--chat", action="store_true", help="Interactive chat loop")
    args = parser.parse_args()

    runtime = AgentRuntime(repo_path=Path(args.repo), retry_limit=args.retry)

    if args.healthcheck:
        rows = runtime.executor_health()
        print("Executor health:")
        for name, ok in rows.items():
            print(f"- {name}: {'ok' if ok else 'unavailable'}")
        return

    if args.chat:
        executor = args.executor or _choose_executor(runtime)
        _chat_loop(runtime, executor=executor, strict=args.strict_executor)
        return

    goal = args.goal or input("Enter task goal: ").strip()
    if _should_quick_reply(goal):
        print(_quick_reply(goal))
        return
    result = runtime.run_task(
        goal=goal,
        constraints=args.constraint,
        executor_override=args.executor or "collab_agent",
        fallback_to_shell=not args.strict_executor,
        conversation_history=[],
    )
    _print_result(result)


if __name__ == "__main__":
    run_cli()
