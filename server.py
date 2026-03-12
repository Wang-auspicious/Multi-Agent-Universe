from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import json
import logging
import os
import re
import subprocess
import traceback
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import APIStatusError, AsyncOpenAI
import tomllib
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_os.tools.permissions import PermissionPolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger("headless-agent-brain")
WORKSPACE_ROOT = Path(__file__).resolve().parent
DEFAULT_EDIT_TARGET = WORKSPACE_ROOT / "data" / "mock_agent_output.py"
PERMISSION_TIMEOUT_SECONDS = 300
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
SHELL_POLICY = PermissionPolicy(repo_path=WORKSPACE_ROOT)
SYSTEM_PROMPT = """You are an AI assistant in a specialized CLI environment, based on the Gemini CLI architecture.

# Core Mandates:
- **Concise & Direct:** Adopt a professional, direct, and concise tone. Avoid conversational filler and apologies.
- **High-Signal Output:** Focus exclusively on intent and technical rationale.
- **Context Efficiency:** Minimize unnecessary context usage.
- **Technical Integrity:** Prioritize readability and long-term maintainability. Align strictly with the requested architectural direction.
- **Engineering Standards:** Follow local conventions, architectural patterns, and style (naming, formatting).

# Operational Rules:
- Use tools like `grep_search` and `list_directory` extensively to understand the codebase.
- Prefer `replace` for surgical edits over `write_file` for large files.
- Before making manual code changes, check if ecosystem tools (like 'eslint --fix', 'prettier --write') are available.
- Fulfill requests thoroughly, including adding tests.
- Do not provide summaries unless asked.

# Execution Workflow:
Operate using a **Research -> Strategy -> Execution** lifecycle.
1. **Research:** Map the codebase and validate assumptions.
2. **Strategy:** Share a concise summary of your plan.
3. **Execution:** Apply targeted changes and validate them.
"""
DEFAULT_TOOL_TIMEOUT_SECONDS = 30
DEFAULT_DIRECTORY_LIST_LIMIT = 200
READ_ONLY_COMMAND_ROOTS = {
    "cat",
    "dir",
    "find",
    "findstr",
    "gc",
    "gci",
    "get-childitem",
    "get-content",
    "get-location",
    "git",
    "ls",
    "node",
    "npm",
    "pnpm",
    "pwd",
    "py",
    "pytest",
    "python",
    "resolve-path",
    "rg",
    "ripgrep",
    "select-string",
    "tree",
    "type",
    "where",
}
BLOCKED_COMMAND_PATTERNS = (
    r"(^|[|;&])\s*curl(\.exe)?\b",
    r"(^|[|;&])\s*invoke-webrequest\b",
    r"(^|[|;&])\s*irm\b",
    r"(^|[|;&])\s*new-item\b",
    r"(^|[|;&])\s*ni\b",
    r"(^|[|;&])\s*remove-item\b",
    r"(^|[|;&])\s*ri\b",
    r"(^|[|;&])\s*rename-item\b",
    r"(^|[|;&])\s*ren\b",
    r"(^|[|;&])\s*set-content\b",
    r"(^|[|;&])\s*sc\b",
    r"(^|[|;&])\s*set-item\b",
    r"(^|[|;&])\s*si\b",
)
RUN_COMMAND_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run a read-only workspace command for inspection, counting, searching, or status checks. Use it instead of writing helper scripts when a shell command can answer the question directly.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "A read-only shell command to run inside the workspace."},
                "reason": {"type": "string", "description": "Short explanation of why the command is needed."},
                "description": {"type": "string", "description": "Optional Gemini-style description of the command's purpose."},
                "dir_path": {"type": "string", "description": "Optional workspace-relative directory to run the command in."},
                "timeout_s": {"type": "integer", "description": "Optional timeout in seconds.", "default": 30},
            },
            "required": ["command"],
        },
    },
}
LIST_DIRECTORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "List files and folders inside the workspace to inspect directory structure without modifying anything.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path or workspace-relative directory path to inspect."},
                "dir_path": {"type": "string", "description": "Gemini-compatible alias for path."},
                "recursive": {"type": "boolean", "description": "Whether to walk into subdirectories.", "default": False},
                "max_depth": {"type": "integer", "description": "Maximum recursion depth when recursive is true. Depth 0 means only the target directory itself.", "default": 2},
                "limit": {"type": "integer", "description": "Maximum number of entries to return.", "default": DEFAULT_DIRECTORY_LIST_LIMIT},
                "include_hidden": {"type": "boolean", "description": "Whether to include hidden files and folders such as .git.", "default": False},
                "ignore": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional glob-style patterns to omit from results, such as ['*.pyc', '__pycache__'].",
                },
                "reason": {"type": "string", "description": "Short explanation of why the directory listing is needed."},
            },
        },
    },
}
WRITE_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write or append UTF-8 text content to a workspace file after user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path or workspace-relative path to write."},
                "content": {"type": "string", "description": "Full UTF-8 content to write or append."},
                "operation": {
                    "type": "string",
                    "enum": ["write", "append"],
                    "description": "Whether to overwrite or append to the file.",
                    "default": "write",
                },
                "reason": {"type": "string", "description": "Short explanation of why this file change is needed."},
            },
            "required": ["path", "content"],
        },
    },
}

READ_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Reads the content of a file. Supports reading specific line ranges for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read."},
                "start_line": {"type": "integer", "description": "Optional: The 1-based line number to start reading from.", "minimum": 1},
                "end_line": {"type": "integer", "description": "Optional: The 1-based line number to end reading at (inclusive)."},
            },
            "required": ["file_path"],
        },
    },
}

GREP_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "grep_search",
        "description": "Searches for a pattern within file contents, similar to ripgrep. Optimized for speed.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The regular expression pattern to search for."},
                "include_pattern": {"type": "string", "description": "Optional: Glob pattern to filter files (e.g., '*.ts')."},
                "dir_path": {"type": "string", "description": "Optional: Directory to search in. Defaults to workspace root."},
                "context": {"type": "integer", "description": "Optional: Number of lines of context to show around each match.", "default": 0},
            },
            "required": ["pattern"],
        },
    },
}

REPLACE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "replace",
        "description": "Replaces text within a file using exact string matching. Best for surgical edits. Requires providing significant context in old_string to ensure uniqueness.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to modify."},
                "old_string": {"type": "string", "description": "The exact literal text to find and replace. Must be unique in the file unless allow_multiple is true."},
                "new_string": {"type": "string", "description": "The text to replace old_string with."},
                "allow_multiple": {"type": "boolean", "description": "If true, replaces all occurrences. If false, fails if old_string is not unique.", "default": False},
                "reason": {"type": "string", "description": "Short explanation of why this change is needed."},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
}

GLOB_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "glob",
        "description": "Finds files matching specific glob patterns (e.g., 'src/**/*.ts', 'docs/*.md').",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The glob pattern to match against (e.g., '**/*.py')."},
                "dir_path": {"type": "string", "description": "Optional: The directory to search within. Defaults to root."},
                "include_hidden": {"type": "boolean", "description": "Whether to search hidden files.", "default": False},
            },
            "required": ["pattern"],
        },
    },
}

READ_MANY_FILES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_many_files",
        "description": "Reads the content of multiple files at once. Optimized for quick context gathering.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read.",
                },
            },
            "required": ["file_paths"],
        },
    },
}

ASK_USER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "Ask the user a question and wait for a text response. Use this when you need clarification, more information, or to make a decision that requires human input.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user."},
            },
            "required": ["question"],
        },
    },
}

WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetches and extracts text from a URL. Useful for reading documentation or raw code from the internet. Only supports HTTP/HTTPS.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "instructions": {"type": "string", "description": "Optional instructions on what to extract from the page."},
            },
            "required": ["url"],
        },
    },
}

SAVE_MEMORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "Persists global user preferences or facts across all future sessions. Use this for recurring instructions like coding styles. Do not use for local project context.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "A concise, global fact or preference to remember (e.g., 'User prefers tabs')."},
            },
            "required": ["fact"],
        },
    },
}

WRITE_TODOS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_todos",
        "description": "Writes or updates a TODO.md file in the workspace to track complex, multi-step tasks. Helps maintain focus over long contexts.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The full markdown content of the TODO list."},
            },
            "required": ["content"],
        },
    },
}

ACTIVATE_SKILL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "activate_skill",
        "description": "Activates a specialized agent skill by name (e.g., 'test-writer', 'pr-creator'). Returns the skill's instructions wrapped in <activated_skill> tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name of the skill to activate."},
            },
            "required": ["name"],
        },
    },
}

SUBAGENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delegate_to_subagent",
        "description": "Delegates a complex, multi-step, or turn-intensive task to a specialized subagent. The subagent operates autonomously and returns a comprehensive summary. Highly recommended to save main context window.",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_name": {
                    "type": "string", 
                    "enum": ["codebase_investigator", "generalist"],
                    "description": "The type of subagent to invoke. codebase_investigator for mapping/architecture, generalist for batch tasks."
                },
                "objective": {"type": "string", "description": "A comprehensive and detailed description of the task for the subagent."},
            },
            "required": ["subagent_name", "objective"],
        },
    },
}

REGISTERED_TOOLS: list[dict[str, Any]] = [
    RUN_COMMAND_TOOL,
    LIST_DIRECTORY_TOOL,
    WRITE_FILE_TOOL,
    READ_FILE_TOOL,
    GREP_SEARCH_TOOL,
    REPLACE_TOOL,
    GLOB_TOOL,
    READ_MANY_FILES_TOOL,
    ASK_USER_TOOL,
    WEB_FETCH_TOOL,
    SAVE_MEMORY_TOOL,
    WRITE_TODOS_TOOL,
    ACTIVATE_SKILL_TOOL,
    SUBAGENT_TOOL,
]
class MessageType(str, Enum):
    THOUGHT = "thought"
    CONTENT = "content"
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"
    ASK_USER = "ask_user"
    ASK_USER_RESPONSE = "ask_user_response"
    FILE_EDIT = "file_edit"
    FINAL_ANSWER = "final_answer"

class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str
    msg_type: MessageType
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)

@dataclass
class ClientSession:
    websocket: WebSocket
    send_queue: asyncio.Queue[AgentMessage] = field(default_factory=asyncio.Queue)
    sender_task: asyncio.Task[None] | None = None
    background_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        session = ClientSession(websocket=websocket)
        session.sender_task = asyncio.create_task(self._sender_loop(client_id, session), name=f"ws-sender-{client_id}")
        async with self._lock:
            self._connections[client_id] = session
        LOGGER.info("Client connected: %s", client_id)

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            session = self._connections.pop(client_id, None)
        if session is None:
            return
        for task in list(session.background_tasks):
            task.cancel()
        if session.background_tasks:
            await asyncio.gather(*session.background_tasks, return_exceptions=True)
        if session.sender_task is not None:
            session.sender_task.cancel()
            if session.sender_task is not asyncio.current_task():
                with contextlib.suppress(asyncio.CancelledError):
                    await session.sender_task
        LOGGER.info("Client disconnected: %s", client_id)

    async def send_to(self, client_id: str, message: AgentMessage) -> bool:
        async with self._lock:
            session = self._connections.get(client_id)
        if session is None:
            return False
        await session.send_queue.put(message)
        return True

    async def register_task(self, client_id: str, task: asyncio.Task[Any]) -> bool:
        async with self._lock:
            session = self._connections.get(client_id)
            if session is None:
                task.cancel()
                return False
            session.background_tasks.add(task)
        task.add_done_callback(lambda finished, cid=client_id: self._discard_task(cid, finished))
        return True

    def _discard_task(self, client_id: str, task: asyncio.Task[Any]) -> None:
        async def _remove() -> None:
            async with self._lock:
                session = self._connections.get(client_id)
                if session is not None:
                    session.background_tasks.discard(task)
        with contextlib.suppress(RuntimeError):
            asyncio.create_task(_remove())

    async def _sender_loop(self, client_id: str, session: ClientSession) -> None:
        try:
            while True:
                message = await session.send_queue.get()
                await session.websocket.send_text(message.model_dump_json())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Socket send failed for %s: %s", client_id, exc)
            await self.disconnect(client_id)

class PermissionRegistry:
    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()

    async def create(self, request_id: str) -> asyncio.Future[Any]:
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._futures[request_id] = future
        return future

    async def resolve(self, request_id: str, result: Any) -> bool:
        async with self._lock:
            future = self._futures.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(result)
        return True

    async def discard(self, request_id: str) -> None:
        async with self._lock:
            self._futures.pop(request_id, None)

@dataclass
class LLMConfig:
    model: str
    base_url: str
    api_key: str
    reasoning_effort: str = "high"
    verbosity: str = "high"

@dataclass
class ConversationState:
    last_response_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

@dataclass
class ChatCompletionStreamState:
    response_id: str | None = None
    model: str | None = None
    text_chunks: list[str] = field(default_factory=list)
    tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)
    saw_chat_chunk: bool = False
    completed: bool = False

class ResponsesLLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url="https://api.deepseek.com",
            timeout=60.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream_response_events(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str,
    ):
        chat_state = ChatCompletionStreamState()
        try:
            response = await self._client.chat.completions.create(
                model="deepseek-chat",
                messages=self._build_chat_messages(messages, instructions),
                tools=self._sanitize_tools(tools),
                stream=True,
            )
            async for chunk in response:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                content = getattr(delta, "content", None) or ""
                reasoning = getattr(delta, "reasoning", None)
                if reasoning is None:
                    reasoning = getattr(delta, "reasoning_content", None)
                tool_calls = getattr(delta, "tool_calls", None) or []
                if not content and not reasoning and not tool_calls:
                    continue

                chunk_dict = self._coerce_sdk_chunk(chunk)
                if chunk_dict is None:
                    continue
                for normalized in self._normalize_chat_completion_chunk(chunk_dict, chat_state):
                    yield normalized
        except APIStatusError as exc:
            LOGGER.error("API error details: %s", getattr(exc, "body", None))
            raise
        except BaseException as e:
            LOGGER.error("Stream parsing failed: %r", e)
            raise

        synthetic_completion = self._build_synthetic_chat_completion(chat_state)
        if synthetic_completion is not None:
            yield synthetic_completion

    def _build_chat_messages(self, messages: list[dict[str, Any]], instructions: str) -> list[dict[str, Any]]:
        built_messages: list[dict[str, Any]] = []
        if instructions:
            built_messages.append({"role": "system", "content": instructions})
        for message in messages:
            normalized = self._normalize_chat_message(message)
            if normalized is not None:
                built_messages.append(normalized)
        return built_messages

    def _sanitize_tools(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._sanitize_tools(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._sanitize_tools(item)
                for key, item in value.items()
                if key not in {"strict", "additionalProperties"}
            }
        return value

    def _normalize_chat_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return None
        item_type = str(message.get("type") or "")
        if item_type == "function_call_output":
            return {
                "role": "tool",
                "tool_call_id": str(message.get("call_id") or ""),
                "content": str(message.get("output") or ""),
            }

        role = str(message.get("role") or "")
        if role not in {"system", "user", "assistant", "tool"}:
            return None

        normalized: dict[str, Any] = {"role": role}
        if "tool_calls" in message:
            normalized["tool_calls"] = message.get("tool_calls") or []
            normalized["content"] = str(message.get("content") or "")
            return normalized
        if role == "tool":
            normalized["tool_call_id"] = str(message.get("tool_call_id") or message.get("call_id") or "")
            normalized["content"] = str(message.get("content") or message.get("output") or "")
            return normalized

        content = message.get("content")
        if isinstance(content, str):
            normalized["content"] = content
            return normalized
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
            normalized["content"] = "".join(parts)
            return normalized
        normalized["content"] = ""
        return normalized

    def _coerce_sdk_chunk(self, chunk: Any) -> dict[str, Any] | None:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return None

        chunk_dict: dict[str, Any] = {
            "id": str(getattr(chunk, "id", "") or ""),
            "model": str(getattr(chunk, "model", "") or ""),
            "choices": [],
        }

        for choice in choices:
            delta = getattr(choice, "delta", None)
            message = getattr(choice, "message", None)
            source = delta if delta is not None else message
            if source is None:
                continue

            content = getattr(source, "content", None) or ""
            reasoning = getattr(source, "reasoning", None)
            if reasoning is None:
                reasoning = getattr(source, "reasoning_content", None)
            tool_calls = []
            for tool_call in getattr(source, "tool_calls", None) or []:
                function = getattr(tool_call, "function", None)
                tool_calls.append(
                    {
                        "index": getattr(tool_call, "index", None),
                        "id": getattr(tool_call, "id", None),
                        "function": {
                            "name": getattr(function, "name", None) if function is not None else None,
                            "arguments": getattr(function, "arguments", None) if function is not None else None,
                        },
                    }
                )

            chunk_dict["choices"].append(
                {
                    "delta": {
                        "content": content,
                        "reasoning": reasoning,
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": getattr(choice, "finish_reason", None),
                }
            )

        if not chunk_dict["choices"]:
            return None
        return chunk_dict

    def _normalize_chat_completion_chunk(
        self,
        chunk: dict[str, Any],
        chat_state: ChatCompletionStreamState,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        chat_state.saw_chat_chunk = True
        chat_state.response_id = str(chunk.get("id") or chat_state.response_id or "")
        chat_state.model = str(chunk.get("model") or chat_state.model or self.config.model)

        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or choice.get("message") or {}
            if not isinstance(delta, dict):
                delta = {}

            output_text = self._coerce_delta_text(delta.get("content"))
            if output_text:
                chat_state.text_chunks.append(output_text)
                events.append({"type": "response.output_text.delta", "delta": output_text, "raw": chunk})

            reasoning_text = self._coerce_delta_text(delta.get("reasoning")) or self._coerce_delta_text(delta.get("reasoning_content"))
            if reasoning_text:
                events.append({"type": "response.reasoning_text.delta", "delta": reasoning_text, "raw": chunk})

            for tool_call in delta.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                merged = self._merge_tool_call_delta(chat_state, tool_call)
                if merged.get("name") and not merged.get("announced"):
                    merged["announced"] = True
                    events.append(
                        {
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call",
                                "id": merged.get("id"),
                                "call_id": merged.get("call_id"),
                                "name": merged.get("name"),
                                "arguments": merged.get("arguments", ""),
                            },
                            "raw": chunk,
                        }
                    )

            if str(choice.get("finish_reason") or "") == "tool_calls":
                for tool_call in chat_state.tool_calls.values():
                    if tool_call.get("done_announced"):
                        continue
                    tool_call["done_announced"] = True
                    events.append(
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "function_call",
                                "id": tool_call.get("id"),
                                "call_id": tool_call.get("call_id"),
                                "name": tool_call.get("name"),
                                "arguments": tool_call.get("arguments", ""),
                            },
                            "raw": chunk,
                        }
                    )
        return events

    def _build_synthetic_chat_completion(self, chat_state: ChatCompletionStreamState) -> dict[str, Any] | None:
        if not chat_state.saw_chat_chunk or chat_state.completed:
            return None
        chat_state.completed = True
        output_text = "".join(chat_state.text_chunks)
        output_items: list[dict[str, Any]] = []
        if output_text:
            output_items.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text}],
            })
        for tool_call in sorted(chat_state.tool_calls.values(), key=lambda item: int(item.get("index", 0))):
            output_items.append({
                "type": "function_call",
                "id": tool_call.get("id") or uuid4().hex,
                "call_id": tool_call.get("call_id") or tool_call.get("id") or uuid4().hex,
                "name": tool_call.get("name") or "unknown_tool",
                "arguments": tool_call.get("arguments", ""),
            })
        return {
            "type": "response.completed",
            "response": {
                "id": chat_state.response_id or uuid4().hex,
                "model": chat_state.model or self.config.model,
                "output_text": output_text,
                "output": output_items,
            },
        }

    def _merge_tool_call_delta(self, chat_state: ChatCompletionStreamState, tool_call: dict[str, Any]) -> dict[str, Any]:
        raw_index = tool_call.get("index")
        try:
            index = int(raw_index) if raw_index is not None else len(chat_state.tool_calls)
        except (TypeError, ValueError):
            index = len(chat_state.tool_calls)
        current = chat_state.tool_calls.setdefault(index, {
            "index": index,
            "id": tool_call.get("id") or uuid4().hex,
            "call_id": tool_call.get("id") or uuid4().hex,
            "name": "",
            "arguments": "",
            "announced": False,
            "done_announced": False,
        })
        current["id"] = tool_call.get("id") or current["id"]
        current["call_id"] = current["id"]
        function_block = tool_call.get("function") or {}
        if isinstance(function_block, dict):
            current["name"] = function_block.get("name") or current["name"]
            current["arguments"] += str(function_block.get("arguments") or "")
        return current

    def _coerce_delta_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            return value["text"]
        return ""

class BrainOrchestrator:
    def __init__(self, *, manager: ConnectionManager, permissions: PermissionRegistry, llm: ResponsesLLMClient) -> None:
        self.manager = manager
        self.permissions = permissions
        self.llm = llm
        self._conversations: dict[str, ConversationState] = {}
        self._conversation_lock = asyncio.Lock()

    async def get_conversation(self, client_id: str) -> ConversationState:
        async with self._conversation_lock:
            return self._conversations.setdefault(client_id, ConversationState())

    async def drop_conversation(self, client_id: str) -> None:
        async with self._conversation_lock:
            self._conversations.pop(client_id, None)

    async def handle_user_task(self, client_id: str, message: AgentMessage) -> None:
        run_id = uuid4().hex
        conversation = await self.get_conversation(client_id)
        conversation.messages.append({"role": "user", "content": message.content})
        final_text = ""
        final_meta: dict[str, Any] = {"status": "completed"}
        streamed_output_chunks: list[str] = []

        try:
            final_text, turn_meta = await self._run_turn_loop(
                client_id=client_id,
                conversation=conversation,
                run_id=run_id,
                requested_by=message.sender,
                streamed_output_chunks=streamed_output_chunks,
            )
            final_meta.update(turn_meta)
        except asyncio.CancelledError:
            LOGGER.info("LLM workflow cancelled for client %s", client_id)
            final_text = "".join(streamed_output_chunks).strip() or "Task cancelled before completion."
            final_meta["status"] = "cancelled"
        except Exception as exc:
            trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            LOGGER.exception("LLM workflow crashed for client %s", client_id)
            final_text = "".join(streamed_output_chunks).strip() or "LLM workflow crashed before completion."
            final_meta["status"] = "error"
            final_meta["error"] = trace
        finally:
            await self.manager.send_to(
                client_id,
                _build_message(
                    "brain",
                    MessageType.FINAL_ANSWER,
                    final_text.strip() or "Task finished without a final text payload.",
                    run_id=run_id,
                    requested_by=message.sender,
                    **final_meta,
                ),
            )

    async def _run_turn_loop(
        self,
        *,
        client_id: str,
        conversation: ConversationState,
        run_id: str,
        requested_by: str,
        streamed_output_chunks: list[str],
        sender_name: str = "brain",
        max_turns: int = 50,
    ) -> tuple[str, dict[str, Any]]:
        turn_count = 0
        while turn_count < max_turns:
            turn_count += 1
            streamed_output_chunks.clear()
            response = await self._stream_llm_turn(
                client_id=client_id,
                run_id=run_id,
                requested_by=requested_by,
                messages=conversation.messages,
                streamed_output_chunks=streamed_output_chunks,
                sender_name=sender_name,
            )
            response_id = str(response.get("id") or conversation.last_response_id or "")
            if response_id:
                conversation.last_response_id = response_id
            tool_outputs = await self._handle_tool_calls(
                client_id=client_id,
                response=response,
                run_id=run_id,
                requested_by=requested_by,
                sender_name=sender_name,
            )
            if tool_outputs:
                assistant_tool_call_message = self._build_assistant_tool_call_message(response)
                if assistant_tool_call_message is not None:
                    conversation.messages.append(assistant_tool_call_message)
                conversation.messages.extend(self._tool_outputs_to_messages(tool_outputs))
                continue
            final_text = self._extract_output_text(response).strip() or "".join(streamed_output_chunks).strip() or "Task finished without a final text payload."
            conversation.messages.append({"role": "assistant", "content": final_text})
            return final_text, {
                "status": "completed",
                "model": response.get("model", self.llm.config.model),
                "response_id": response.get("id"),
            }
        return "Task aborted: Exceeded maximum allowed turns.", {"status": "error", "error": "max_turns_exceeded"}

    async def _stream_llm_turn(
        self,
        *,
        client_id: str,
        run_id: str,
        requested_by: str,
        messages: list[dict[str, Any]],
        streamed_output_chunks: list[str],
        sender_name: str = "brain",
    ) -> dict[str, Any]:
        final_response: dict[str, Any] | None = None
        response_id: str | None = None
        response_model: str | None = self.llm.config.model
        pending_tool_calls: dict[str, dict[str, Any]] = {}
        stream_request_id = uuid4().hex
        thought_id = f"thought-{uuid4().hex[:8]}"
        full_text = ""
        buffer = "" # Semantic buffer
        streamed_output_chunks.clear()

        async for event in self.llm.stream_response_events(
            messages=messages,
            tools=REGISTERED_TOOLS,
            instructions=SYSTEM_PROMPT,
        ):
            event_type = str(event.get("type", ""))
            response_payload = event.get("response") or {}
            if isinstance(response_payload, dict):
                response_id = str(response_payload.get("id") or response_id or "")
                response_model = str(response_payload.get("model") or response_model or self.llm.config.model)

            if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                content = str(event.get("delta", "") or "")
                if not content:
                    continue
                full_text += content
                buffer += content

                # Send when buffer has a newline or is long enough
                if "\n" in buffer or len(buffer) > 60:
                    lines = buffer.split("\n")
                    for line in lines[:-1]:
                        # Send the line as CONTENT for proper terminal/UI rendering
                        await _send_status(
                            client_id, sender_name, MessageType.CONTENT, line + "\n",
                            run_id=run_id, requested_by=requested_by,
                            stream_event=event_type, stream_request_id=stream_request_id,
                            thought_id=thought_id, channel="output", is_delta=True
                        )
                    buffer = lines[-1]

                streamed_output_chunks.clear()
                streamed_output_chunks.append(full_text)
            elif event_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                delta = str(event.get("delta", "") or "")
                if delta:
                    # Format reasoning as a thought with a bold subject for better UI display
                    await _send_status(client_id, sender_name, MessageType.THOUGHT, f"**Thinking** {delta}", run_id=run_id, requested_by=requested_by, stream_event=event_type, stream_request_id=stream_request_id, channel="reasoning", thought_id=thought_id, is_delta=True)
            elif event_type == "response.output_item.added":
                # Flush buffer before tool call
                if buffer.strip():
                    await _send_status(client_id, sender_name, MessageType.CONTENT, buffer, run_id=run_id, requested_by=requested_by, stream_event="response.output_text.delta", stream_request_id=stream_request_id, thought_id=thought_id, channel="output", is_delta=True)
                    buffer = ""
                
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    call_id = str(item.get("call_id") or item.get("id") or uuid4().hex)
                    pending_tool_calls[call_id] = {
                        "type": "function_call",
                        "id": item.get("id") or call_id,
                        "call_id": call_id,
                        "name": item.get("name") or "unknown",
                        "arguments": str(item.get("arguments") or ""),
                    }
                    # Use **Executing** format for tool calls to trigger the Step UI in Gemini CLI
                    await _send_status(client_id, sender_name, MessageType.THOUGHT, f"**Executing** {item.get('name', 'unknown')}", run_id=run_id, requested_by=requested_by, stream_event=event_type, stream_request_id=stream_request_id, thought_id=thought_id, channel="status", update_mode="replace")
            elif event_type == "response.completed":
                # Final flush
                if buffer.strip():
                    await _send_status(client_id, sender_name, MessageType.CONTENT, buffer, run_id=run_id, requested_by=requested_by, stream_event="response.output_text.delta", stream_request_id=stream_request_id, thought_id=thought_id, channel="output", is_delta=True)
                final_response = dict(event.get("response") or {})

            elif event_type.endswith(".done") and isinstance(event.get("item"), dict):
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    call_id = str(item.get("call_id") or item.get("id") or uuid4().hex)
                    pending_tool_calls[call_id] = {
                        "type": "function_call",
                        "id": item.get("id") or call_id,
                        "call_id": call_id,
                        "name": item.get("name") or "unknown",
                        "arguments": str(item.get("arguments") or ""),
                    }
                    # We don't send a separate status for done to keep it compact

        if final_response is None and (full_text or pending_tool_calls):
            output_items: list[dict[str, Any]] = []
            if full_text:
                output_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": full_text}],
                })
            output_items.extend(pending_tool_calls.values())
            final_response = {
                "id": response_id or uuid4().hex,
                "model": response_model or self.llm.config.model,
                "output_text": full_text,
                "output": output_items,
            }

        if final_response is not None and full_text:
            final_response["output_text"] = full_text
            output = final_response.get("output") or []
            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict) or item.get("type") != "message":
                        continue
                    item["content"] = [{"type": "output_text", "text": full_text}]
                    break

        if final_response is None:
            raise RuntimeError("No final response object was produced by the LLM stream.")
        return final_response

    def _build_assistant_tool_call_message(self, response: dict[str, Any]) -> dict[str, Any] | None:
        tool_calls: list[dict[str, Any]] = []
        for item in response.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            call_id = str(item.get("call_id") or item.get("id") or uuid4().hex)
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": str(item.get("name") or "unknown"),
                    "arguments": str(item.get("arguments") or ""),
                },
            })
        if not tool_calls:
            return None
        return {"role": "assistant", "content": "", "tool_calls": tool_calls}

    def _tool_outputs_to_messages(self, tool_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in tool_outputs:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "function_call_output":
                continue
            messages.append({
                "role": "tool",
                "tool_call_id": str(item.get("call_id") or ""),
                "content": str(item.get("output") or ""),
            })
        return messages


    async def _handle_tool_calls(
        self,
        *,
        client_id: str,
        response: dict[str, Any],
        run_id: str,
        requested_by: str,
        sender_name: str = "brain",
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        handlers = {
            "run_command": self._run_command_tool,
            "list_directory": self._run_list_directory_tool,
            "write_file": self._run_write_file_tool,
            "read_file": self._run_read_file_tool,
            "grep_search": self._run_grep_search_tool,
            "replace": self._run_replace_tool,
            "glob": self._run_glob_tool,
            "read_many_files": self._run_read_many_files_tool,
            "ask_user": self._run_ask_user_tool,
            "web_fetch": self._run_web_fetch_tool,
            "save_memory": self._run_save_memory_tool,
            "write_todos": self._run_write_todos_tool,
            "activate_skill": self._run_activate_skill_tool,
            "delegate_to_subagent": self._run_subagent_tool,
        }
        for item in response.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            tool_name = str(item.get("name", ""))
            call_id = str(item.get("call_id") or item.get("id") or uuid4().hex)
            handler = handlers.get(tool_name)
            if handler is None:
                tool_result = {"ok": False, "error": f"Unknown tool {tool_name}."}
            else:
                # Some tools need extra context (like subagent), most don't. We pass standard kwargs.
                kwargs = {
                    "client_id": client_id,
                    "arguments_raw": str(item.get("arguments", "") or "{}"),
                    "run_id": run_id,
                    "requested_by": requested_by,
                }
                if tool_name == "delegate_to_subagent":
                    kwargs["sender_name"] = sender_name
                
                tool_result = await handler(**kwargs)
            outputs.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(tool_result, ensure_ascii=False),
            })
        return outputs

    async def _run_activate_skill_tool(self, *, client_id: str, arguments_raw: str, run_id: str, requested_by: str) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None: return error
        skill_name = str(arguments.get("name") or "")
        await _send_status(client_id, "brain", MessageType.THOUGHT, f"**Activating** skill: {skill_name}...", run_id=run_id, requested_by=requested_by, tool_name="activate_skill", kind="tool_running")
        return _execute_activate_skill(arguments)

    async def _run_subagent_tool(self, *, client_id: str, arguments_raw: str, run_id: str, requested_by: str, sender_name: str) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None: return error
        
        subagent_name = str(arguments.get("subagent_name") or "subagent")
        objective = str(arguments.get("objective") or "")
        
        if sender_name != "brain":
             return {"ok": False, "error": "Nested subagents are not allowed to prevent infinite recursion."}
        
        await _send_status(client_id, "brain", MessageType.THOUGHT, f"🚀 Delegating to Subagent: {subagent_name}\nObjective: {objective}", run_id=run_id, requested_by=requested_by, tool_name="delegate_to_subagent", kind="tool_running")
        
        # Create an isolated conversation for the subagent
        sub_conversation = ConversationState()
        sub_instructions = f"You are an expert subagent named '{subagent_name}'. Your objective is:\n<objective>\n{objective}\n</objective>\nUse your tools to investigate or execute tasks. When finished, provide a comprehensive summary of your findings or actions to the main agent. Do NOT ask the user questions unless absolutely blocked."
        sub_conversation.messages.append({"role": "system", "content": sub_instructions})
        sub_conversation.messages.append({"role": "user", "content": "Begin your objective now."})
        
        sub_streamed_chunks = []
        try:
            # We run the turn loop but pass the subagent_name so UI shows it differently
            final_report, _ = await self._run_turn_loop(
                client_id=client_id,
                conversation=sub_conversation,
                run_id=run_id,
                requested_by=requested_by,
                streamed_output_chunks=sub_streamed_chunks,
                sender_name=f"subagent-{subagent_name}",
                max_turns=15 # Safety limit for subagents
            )
            await _send_status(client_id, "brain", MessageType.THOUGHT, f"✅ Subagent {subagent_name} finished.", run_id=run_id, requested_by=requested_by, tool_name="delegate_to_subagent", kind="tool_done")
            return {"ok": True, "subagent": subagent_name, "report": final_report}
        except Exception as exc:
             return {"ok": False, "error": f"Subagent crashed: {exc}"}

    async def _run_web_fetch_tool(self, *, client_id: str, arguments_raw: str, run_id: str, requested_by: str) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None: return error
        url = str(arguments.get("url") or "")
        await _send_status(client_id, "brain", MessageType.THOUGHT, f"**Fetching** URL: {url}", run_id=run_id, requested_by=requested_by, tool_name="web_fetch", kind="tool_running")
        return _execute_web_fetch(arguments)

    async def _run_save_memory_tool(self, *, client_id: str, arguments_raw: str, run_id: str, requested_by: str) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None: return error
        fact = str(arguments.get("fact") or "")
        await _send_status(client_id, "brain", MessageType.THOUGHT, f"Saving to memory: {fact}", run_id=run_id, requested_by=requested_by, tool_name="save_memory", kind="tool_running")
        return _execute_save_memory(arguments)

    async def _run_write_todos_tool(self, *, client_id: str, arguments_raw: str, run_id: str, requested_by: str) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None: return error
        await _send_status(client_id, "brain", MessageType.THOUGHT, "Updating TODO.md...", run_id=run_id, requested_by=requested_by, tool_name="write_todos", kind="tool_running")
        return _execute_write_todos(arguments)

    async def _run_ask_user_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[dict[str, Any]]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        question = str(arguments.get("question") or "No question provided.")
        request_id = uuid4().hex
        response_future = await self.permissions.create(request_id)
        
        await manager.send_to(
            client_id,
            _build_message(
                "brain",
                MessageType.ASK_USER,
                question,
                run_id=run_id,
                requested_by=requested_by,
                request_id=request_id,
                tool_name="ask_user",
                kind="user_input_needed",
            ),
        )

        try:
            # Re-using PERMISSION_TIMEOUT_SECONDS for ask_user
            answer = await asyncio.wait_for(response_future, timeout=PERMISSION_TIMEOUT_SECONDS)
            return {"ok": True, "answer": answer, "request_id": request_id}
        except asyncio.TimeoutError:
            await self.permissions.discard(request_id)
            return {"ok": False, "error": "User did not respond within the timeout period.", "request_id": request_id}

    async def _run_glob_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        pattern = str(arguments.get("pattern") or "")
        reason = str(arguments.get("reason") or f"Finding files matching: {pattern}")
        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="glob",
            pattern=pattern,
            kind="tool_running",
        )
        return _execute_glob(arguments)

    async def _run_read_many_files_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        file_paths = arguments.get("file_paths") or []
        reason = str(arguments.get("reason") or f"Reading {len(file_paths)} files batch")
        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="read_many_files",
            count=len(file_paths),
            kind="tool_running",
        )
        return _execute_read_many_files(arguments)

    async def _run_replace_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        path_hint = str(arguments.get("file_path") or "")
        reason = str(arguments.get("reason") or f"Replacing text in {path_hint}")
        request_id = uuid4().hex
        permission_future = await self.permissions.create(request_id)
        await _send_status(
            client_id,
            "brain",
            MessageType.PERMISSION_REQUEST,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            request_id=request_id,
            path=path_hint,
            tool_name="replace",
            warning="Model requested a surgical file edit.",
            kind="approval_needed",
        )

        try:
            approved = await asyncio.wait_for(permission_future, timeout=PERMISSION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self.permissions.discard(request_id)
            return {"ok": False, "approved": False, "request_id": request_id, "error": "Permission request timed out before the user answered."}
        
        if not approved:
            return {"ok": False, "approved": False, "request_id": request_id, "error": "User denied the replace request."}

        result = _execute_replace(arguments)
        if result.get("ok"):
            await self.manager.send_to(
                client_id,
                AgentMessage(
                    sender="brain",
                    msg_type=MessageType.FILE_EDIT,
                    content=str(arguments.get("new_string", "")),
                    meta={"run_id": run_id, "requested_by": requested_by, "request_id": request_id, "tool_name": "replace", **result},
                ),
            )
        return {"ok": result.get("ok", False), "approved": True, "request_id": request_id, **result}

    async def _run_read_file_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        path_hint = str(arguments.get("file_path") or arguments.get("path") or "")
        reason = str(arguments.get("reason") or f"Reading file: {path_hint}")
        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="read_file",
            path=path_hint,
            kind="tool_running",
        )
        return _execute_read_file(arguments)

    async def _run_grep_search_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        pattern = str(arguments.get("pattern") or "")
        reason = str(arguments.get("reason") or f"Searching for pattern: {pattern}")
        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="grep_search",
            pattern=pattern,
            kind="tool_running",
        )
        return _execute_grep_search(arguments)

    async def _run_write_file_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        try:
            arguments = json.loads(arguments_raw or "{}")
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Tool arguments were not valid JSON: {exc}"}

        path_hint = str(arguments.get("path") or "")
        content = str(arguments.get("content") or "")
        operation = str(arguments.get("operation") or "write")
        reason = str(arguments.get("reason") or "Model requested a file write.")
        request_id = uuid4().hex
        permission_future = await self.permissions.create(request_id)
        await _send_status(
            client_id,
            "brain",
            MessageType.PERMISSION_REQUEST,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            request_id=request_id,
            path=path_hint,
            operation=operation,
            tool_name="write_file",
            warning="Model requested a local file edit.",
            kind="approval_needed",
        )

        try:
            approved = await asyncio.wait_for(permission_future, timeout=PERMISSION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self.permissions.discard(request_id)
            return {"ok": False, "approved": False, "request_id": request_id, "error": "Permission request timed out before the user answered."}
        except asyncio.CancelledError:
            await self.permissions.discard(request_id)
            raise

        if not approved:
            return {"ok": False, "approved": False, "request_id": request_id, "error": "User denied the file write request."}

        result = apply_file_edit(path_hint, content, operation)
        await self.manager.send_to(
            client_id,
            AgentMessage(
                sender="brain",
                msg_type=MessageType.FILE_EDIT,
                content=content,
                meta={"run_id": run_id, "requested_by": requested_by, "request_id": request_id, "tool_name": "write_file", **result},
            ),
        )
        return {"ok": True, "approved": True, "request_id": request_id, **result}

    async def _run_command_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        command = str(arguments.get("command") or "").strip()
        reason = str(arguments.get("reason") or "Running a read-only workspace command.")

        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="run_command",
            command=command,
            kind="tool_running",
        )
        return _execute_run_command(arguments)

    async def _run_list_directory_tool(
        self,
        *,
        client_id: str,
        arguments_raw: str,
        run_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        arguments, error = _decode_tool_arguments(arguments_raw)
        if error is not None:
            return error

        path_hint = str(arguments.get("path") or arguments.get("dir_path") or ".")
        reason = str(arguments.get("reason") or f"Listing directory structure for {path_hint}.")
        await _send_status(
            client_id,
            "brain",
            MessageType.THOUGHT,
            reason,
            run_id=run_id,
            requested_by=requested_by,
            tool_name="list_directory",
            path=path_hint,
            kind="tool_running",
        )
        return _execute_list_directory(arguments)

    def _extract_output_text(self, response: dict[str, Any]) -> str:
        direct = str(response.get("output_text", "") or "").strip()
        if direct:
            return direct
        chunks: list[str] = []
        for item in response.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "output_text":
                    text = str(content.get("text", "") or "")
                    if text:
                        chunks.append(text)
                elif content.get("type") == "refusal":
                    refusal = str(content.get("refusal", "") or "")
                    if refusal:
                        chunks.append(refusal)
        return "".join(chunks)

manager = ConnectionManager()
permissions = PermissionRegistry()
app = FastAPI(title="Headless Multi-Agent IDE Brain")


def _load_llm_config() -> LLMConfig:
    config_data: dict[str, Any] = {}
    auth_data: dict[str, Any] = {}
    if CODEX_CONFIG_PATH.exists():
        config_data = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
    if CODEX_AUTH_PATH.exists():
        auth_data = json.loads(CODEX_AUTH_PATH.read_text(encoding="utf-8"))

    provider_name = str(os.getenv("MODEL_PROVIDER") or config_data.get("model_provider") or "deepseek")
    provider_block = dict(config_data.get("model_providers", {}).get(provider_name, {}))
    base_url = str(
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or provider_block.get("base_url")
        or "https://api.deepseek.com"
    )
    api_key = str(
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or provider_block.get("api_key")
        or auth_data.get("DEEPSEEK_API_KEY")
        or "sk-4fda3c6f08544273955394ace6530594"
    )
    model = str(os.getenv("DEEPSEEK_MODEL") or os.getenv("OPENAI_MODEL") or config_data.get("model") or "deepseek-chat")
    reasoning_effort = str(os.getenv("OPENAI_REASONING_EFFORT") or config_data.get("model_reasoning_effort") or "high")
    verbosity = str(os.getenv("OPENAI_VERBOSITY") or config_data.get("model_verbosity") or "high")
    if not api_key:
        raise RuntimeError("DeepSeek API key is not configured. Set DEEPSEEK_API_KEY or ~/.codex/auth.json.")
    return LLMConfig(model=model, base_url=base_url, api_key=api_key, reasoning_effort=reasoning_effort, verbosity=verbosity)


llm_client = ResponsesLLMClient(_load_llm_config())
brain = BrainOrchestrator(manager=manager, permissions=permissions, llm=llm_client)


def _resolve_workspace_path(raw_path: str | None) -> Path:
    if not raw_path:
        return DEFAULT_EDIT_TARGET
    candidate = Path(raw_path)
    resolved = candidate if candidate.is_absolute() else (WORKSPACE_ROOT / candidate)
    resolved = resolved.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Refusing to edit path outside workspace: {resolved}") from exc
    return resolved


def _build_message(sender: str, msg_type: MessageType, content: str, **meta: Any) -> AgentMessage:
    return AgentMessage(sender=sender, msg_type=msg_type, content=content, meta=meta)


async def _send_status(client_id: str, sender: str, msg_type: MessageType, content: str, **meta: Any) -> None:
    await manager.send_to(client_id, _build_message(sender, msg_type, content, **meta))


def _tool_error(message: str, *, error_type: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "error_type": error_type, **extra}


def _decode_tool_arguments(arguments_raw: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        decoded = json.loads(arguments_raw or "{}")
    except json.JSONDecodeError as exc:
        return {}, _tool_error(f"Tool arguments were not valid JSON: {exc}", error_type="invalid_json")
    if not isinstance(decoded, dict):
        return {}, _tool_error("Tool arguments must decode to a JSON object.", error_type="invalid_arguments")
    return decoded, None


def _coerce_int(value: Any, *, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _resolve_directory_path(raw_path: str | None) -> Path:
    candidate = Path(raw_path or ".")
    resolved = candidate if candidate.is_absolute() else (WORKSPACE_ROOT / candidate)
    resolved = resolved.resolve()
    ok, reason = SHELL_POLICY.validate_path(resolved)
    if not ok:
        raise ValueError(reason)
    if not resolved.exists():
        raise FileNotFoundError(f"Directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {resolved}")
    return resolved


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _build_directory_entry(root: Path, entry_path: Path) -> dict[str, Any]:
    stats = entry_path.stat()
    relative = entry_path.relative_to(root)
    return {
        "name": entry_path.name,
        "path": str(entry_path),
        "relative_path": "." if not relative.parts else relative.as_posix(),
        "type": "directory" if entry_path.is_dir() else "file",
        "size": stats.st_size,
        "modified_at": datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc).isoformat(),
    }


def _normalize_ignore_patterns(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _matches_ignore_pattern(relative_path: Path, ignore_patterns: list[str]) -> bool:
    if not ignore_patterns:
        return False
    relative_text = relative_path.as_posix()
    filename = relative_path.name
    return any(
        fnmatch.fnmatch(relative_text, pattern) or fnmatch.fnmatch(filename, pattern)
        for pattern in ignore_patterns
    )


def _iter_directory_entries(
    root: Path,
    *,
    recursive: bool,
    max_depth: int,
    include_hidden: bool,
    ignore_patterns: list[str],
) -> list[Path]:
    entries: list[Path] = []

    def walk(current: Path, depth: int) -> None:
        try:
            children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except PermissionError:
            return
        except OSError:
            return

        for child in children:
            relative_child = child.relative_to(root)
            if not include_hidden and _is_hidden_path(relative_child):
                continue
            if _matches_ignore_pattern(relative_child, ignore_patterns):
                continue
            entries.append(child)
            if recursive and child.is_dir() and depth < max_depth:
                walk(child, depth + 1)

    walk(root, 0)
    return entries


def _execute_glob(arguments: dict[str, Any]) -> dict[str, Any]:
    pattern = str(arguments.get("pattern") or "").strip()
    dir_path = str(arguments.get("dir_path") or ".").strip() or "."
    include_hidden = bool(arguments.get("include_hidden", False))

    if not pattern:
        return _tool_error("glob requires a pattern.", error_type="missing_pattern")

    try:
        resolved_dir = _resolve_directory_path(dir_path)
    except Exception as exc:
        return _tool_error(f"Invalid search directory: {exc}", error_type="invalid_dir", path=dir_path)

    try:
        # Use Path.glob for recursive search if pattern contains **
        results = []
        # Support both simple glob and recursive glob
        search_root = resolved_dir
        
        # Security: ensure search remains within workspace
        for p in search_root.glob(pattern):
            try:
                # Resolve each found path and check workspace relative
                p_resolved = p.resolve()
                if not include_hidden and _is_hidden_path(p_resolved.relative_to(WORKSPACE_ROOT)):
                    continue
                results.append(str(p_resolved.relative_to(WORKSPACE_ROOT)))
            except (ValueError, RuntimeError):
                continue # Skip paths outside workspace or other resolution errors
        
        return {
            "ok": True,
            "pattern": pattern,
            "dir_path": dir_path,
            "matches": sorted(results)[:500], # Limit results to prevent overwhelming
            "total_matches": len(results),
        }
    except Exception as exc:
        return _tool_error(f"Glob search failed: {exc}", error_type="glob_error")


def _execute_read_many_files(arguments: dict[str, Any]) -> dict[str, Any]:
    file_paths = arguments.get("file_paths")
    if not isinstance(file_paths, list):
        return _tool_error("read_many_files requires a list of file_paths.", error_type="invalid_arguments")

    results = []
    total_bytes = 0
    BYTE_LIMIT = 50 * 1024 # 50KB limit for batch reading to protect context
    
    for path_str in file_paths:
        try:
            resolved = _resolve_workspace_path(str(path_str))
            if not resolved.exists() or not resolved.is_file():
                results.append({"path": path_str, "ok": False, "error": "Not found or not a file"})
                continue
            
            content = resolved.read_text(encoding="utf-8", errors="replace")
            file_bytes = len(content.encode("utf-8"))
            
            if total_bytes + file_bytes > BYTE_LIMIT:
                results.append({
                    "path": path_str, 
                    "ok": True, 
                    "content": content[: (BYTE_LIMIT - total_bytes)] + "\n... [TRUNCATED due to batch limit]",
                    "truncated": True
                })
                break # Stop reading further files
            
            results.append({"path": path_str, "ok": True, "content": content, "size": file_bytes})
            total_bytes += file_bytes
        except Exception as exc:
            results.append({"path": str(path_str), "ok": False, "error": str(exc)})

    return {
        "ok": True,
        "files": results,
        "total_files_attempted": len(file_paths),
        "total_bytes_read": total_bytes,
        "byte_limit": BYTE_LIMIT
    }


def _execute_web_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    if not url:
        return _tool_error("web_fetch requires a url.", error_type="missing_url")
    
    if not url.startswith(("http://", "https://")):
        return _tool_error("web_fetch only supports HTTP/HTTPS URLs.", error_type="invalid_url")

    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            content_type = response.headers.get_content_type()
            # Basic check to avoid downloading huge binaries
            if content_type and not any(t in content_type for t in ["text/", "json", "xml"]):
                 return _tool_error(f"Unsupported content type: {content_type}", error_type="unsupported_content")
            
            html = response.read().decode('utf-8', errors='replace')
            
            # Very basic tag stripping for cleaner context
            text = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.IGNORECASE|re.DOTALL)
            text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE|re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Truncate if too long (e.g., > 50KB)
            limit = 50000
            truncated = False
            if len(text) > limit:
                text = text[:limit] + "\n...[TRUNCATED]"
                truncated = True
                
            return {"ok": True, "url": url, "content": text, "truncated": truncated}
    except Exception as exc:
        return _tool_error(f"Failed to fetch URL: {exc}", error_type="fetch_error", url=url)


def _execute_save_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    fact = str(arguments.get("fact") or "").strip()
    if not fact:
        return _tool_error("save_memory requires a fact.", error_type="missing_fact")
        
    memory_file = Path.home() / ".agent_universe" / "memory.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        content = ""
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            
        content += f"\n- {fact}"
        memory_file.write_text(content.strip(), encoding="utf-8")
        
        return {"ok": True, "fact": fact, "saved_to": str(memory_file)}
    except Exception as exc:
        return _tool_error(f"Failed to save memory: {exc}", error_type="memory_error")


def _execute_write_todos(arguments: dict[str, Any]) -> dict[str, Any]:
    content = str(arguments.get("content") or "").strip()
    if not content:
        return _tool_error("write_todos requires content.", error_type="missing_content")
        
    todo_file = WORKSPACE_ROOT / "TODO.md"
    
    try:
        todo_file.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(todo_file), "bytes_written": len(content.encode("utf-8"))}
    except Exception as exc:
        return _tool_error(f"Failed to write TODOs: {exc}", error_type="todo_error")


def _execute_activate_skill(arguments: dict[str, Any]) -> dict[str, Any]:
    skill_name = str(arguments.get("name") or "").strip()
    if not skill_name:
        return _tool_error("activate_skill requires a name.", error_type="missing_name")
        
    skills_dir = WORKSPACE_ROOT / ".agent_universe" / "skills"
    skill_file = skills_dir / f"{skill_name}.md"
    
    if not skill_file.exists():
        # Auto-create a mock skill file for demonstration if it doesn't exist
        skills_dir.mkdir(parents=True, exist_ok=True)
        mock_content = f"""# Skill: {skill_name}\n\nYou are acting as a specialized expert in {skill_name}. Focus strictly on this domain. Provide clear, structural advice and leverage tools effectively."""
        skill_file.write_text(mock_content, encoding="utf-8")
        
    try:
        content = skill_file.read_text(encoding="utf-8")
        wrapped = f"<activated_skill name=\"{skill_name}\">\n{content}\n</activated_skill>"
        return {"ok": True, "skill": skill_name, "instructions": wrapped}
    except Exception as exc:
        return _tool_error(f"Failed to read skill {skill_name}: {exc}", error_type="skill_error")


def _execute_replace(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(arguments.get("file_path") or "").strip()
    old_string = str(arguments.get("old_string") or "")
    new_string = str(arguments.get("new_string") or "")
    allow_multiple = bool(arguments.get("allow_multiple", False))

    if not raw_path:
        return _tool_error("replace requires a file_path.", error_type="missing_path")
    if not old_string:
        return _tool_error("replace requires an old_string to find.", error_type="missing_old_string")

    try:
        resolved = _resolve_workspace_path(raw_path)
    except ValueError as exc:
        return _tool_error(str(exc), error_type="path_not_allowed", path=raw_path)

    if not resolved.exists():
        return _tool_error(f"File not found: {raw_path}", error_type="not_found", path=raw_path)
    
    try:
        content = resolved.read_text(encoding="utf-8")
        count = content.count(old_string)
        
        if count == 0:
            return _tool_error(f"Could not find exact match for old_string in {raw_path}", error_type="no_match")
        if count > 1 and not allow_multiple:
            return _tool_error(f"Found {count} occurrences of old_string in {raw_path}. Provide more context or set allow_multiple=True.", error_type="ambiguous_match", count=count)
        
        new_content = content.replace(old_string, new_string) if allow_multiple else content.replace(old_string, new_string, 1)
        resolved.write_text(new_content, encoding="utf-8")
        
        return {
            "ok": True,
            "path": raw_path,
            "count": count if allow_multiple else 1,
            "operation": "replace",
            "bytes_written": len(new_content.encode("utf-8")),
        }
    except Exception as exc:
        return _tool_error(f"Failed to execute replace: {exc}", error_type="replace_error", path=raw_path)


def _execute_read_file(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(arguments.get("file_path") or arguments.get("path") or "").strip()
    start_line = _coerce_int(arguments.get("start_line"), default=1, minimum=1)
    end_line = _coerce_int(arguments.get("end_line"), default=0, minimum=0)

    if not raw_path:
        return _tool_error("read_file requires a file_path.", error_type="missing_path")

    try:
        resolved = _resolve_workspace_path(raw_path)
    except ValueError as exc:
        return _tool_error(str(exc), error_type="path_not_allowed", path=raw_path)

    if not resolved.exists():
        return _tool_error(f"File not found: {raw_path}", error_type="not_found", path=raw_path)
    if not resolved.is_file():
        return _tool_error(f"Path is not a file: {raw_path}", error_type="not_a_file", path=raw_path)

    try:
        import itertools
        with resolved.open("r", encoding="utf-8", errors="replace") as f:
            if end_line > 0:
                # 1-based to 0-based slice
                lines = list(itertools.islice(f, start_line - 1, end_line))
            else:
                lines = list(itertools.islice(f, start_line - 1, None))
            
            content = "".join(lines)
            return {
                "ok": True,
                "path": raw_path,
                "resolved_path": str(resolved),
                "content": content,
                "start_line": start_line,
                "end_line": end_line if end_line > 0 else (start_line + len(lines) - 1),
                "total_lines_read": len(lines),
            }
    except Exception as exc:
        return _tool_error(f"Failed to read file: {exc}", error_type="read_error", path=raw_path)


def _execute_grep_search(arguments: dict[str, Any]) -> dict[str, Any]:
    pattern = str(arguments.get("pattern") or "").strip()
    include_pattern = str(arguments.get("include_pattern") or "").strip()
    dir_path = str(arguments.get("dir_path") or ".").strip() or "."
    context = _coerce_int(arguments.get("context"), default=0, minimum=0, maximum=10)

    if not pattern:
        return _tool_error("grep_search requires a pattern.", error_type="missing_pattern")

    try:
        resolved_dir = _resolve_directory_path(dir_path)
    except Exception as exc:
        return _tool_error(f"Invalid search directory: {exc}", error_type="invalid_dir", path=dir_path)

    # Try ripgrep first
    try:
        rg_cmd = ["rg", "--json", "-e", pattern]
        if include_pattern:
            rg_cmd.extend(["-g", include_pattern])
        if context > 0:
            rg_cmd.extend(["-C", str(context)])
        rg_cmd.append(str(resolved_dir))

        completed = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode in {0, 1}:  # 0: found, 1: not found
            matches = []
            for line in completed.stdout.splitlines():
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "match":
                        payload = data.get("data", {})
                        matches.append({
                            "path": os.path.relpath(payload.get("path", {}).get("text", ""), str(WORKSPACE_ROOT)),
                            "line_number": payload.get("line_number"),
                            "content": payload.get("lines", {}).get("text", "").strip(),
                            "submatches": payload.get("submatches", [])
                        })
                except: continue
            return {"ok": True, "matches": matches[:100], "total_matches": len(matches), "engine": "ripgrep"}
    except FileNotFoundError:
        pass # rg not installed, fallback to python
    except Exception:
        pass

    # Fallback to Python-based search
    matches = []
    regex = re.compile(pattern, re.IGNORECASE)
    count = 0
    for root, dirs, files in os.walk(resolved_dir):
        # Apply ignore patterns similar to list_directory if needed
        for file in files:
            if include_pattern and not fnmatch.fnmatch(file, include_pattern):
                continue
            full_path = Path(root) / file
            try:
                with full_path.open("r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "path": os.path.relpath(full_path, str(WORKSPACE_ROOT)),
                                "line_number": i,
                                "content": line.strip()
                            })
                            count += 1
                            if count >= 100: break
            except: continue
            if count >= 100: break
        if count >= 100: break
    
    return {"ok": True, "matches": matches, "total_matches": len(matches), "engine": "python_regex"}


def _execute_list_directory(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(arguments.get("path") or arguments.get("dir_path") or ".").strip() or "."
    recursive = bool(arguments.get("recursive", False))
    include_hidden = bool(arguments.get("include_hidden", False))
    max_depth = _coerce_int(arguments.get("max_depth"), default=2, minimum=0, maximum=10)
    limit = _coerce_int(arguments.get("limit"), default=DEFAULT_DIRECTORY_LIST_LIMIT, minimum=1, maximum=1000)
    ignore_patterns = _normalize_ignore_patterns(arguments.get("ignore"))

    try:
        resolved = _resolve_directory_path(raw_path)
    except ValueError as exc:
        return _tool_error(str(exc), error_type="path_not_allowed", path=raw_path)
    except FileNotFoundError as exc:
        return _tool_error(str(exc), error_type="not_found", path=raw_path)
    except NotADirectoryError as exc:
        return _tool_error(str(exc), error_type="not_directory", path=raw_path)
    except OSError as exc:
        return _tool_error(f"Unable to access directory: {exc}", error_type="os_error", path=raw_path)
    except Exception as exc:
        return _tool_error(f"Unexpected directory resolution failure: {exc}", error_type="unexpected_error", path=raw_path)

    try:
        all_entries = _iter_directory_entries(
            resolved,
            recursive=recursive,
            max_depth=max_depth,
            include_hidden=include_hidden,
            ignore_patterns=ignore_patterns,
        )
        returned_entries = all_entries[:limit]
        return {
            "ok": True,
            "path": raw_path,
            "resolved_path": str(resolved),
            "recursive": recursive,
            "max_depth": max_depth if recursive else 0,
            "include_hidden": include_hidden,
            "ignore": ignore_patterns,
            "total_entries": len(all_entries),
            "returned_entries": len(returned_entries),
            "truncated": len(all_entries) > limit,
            "entries": [_build_directory_entry(resolved, entry) for entry in returned_entries],
        }
    except PermissionError as exc:
        return _tool_error(f"Permission denied while listing directory: {exc}", error_type="permission_denied", path=str(resolved))
    except OSError as exc:
        return _tool_error(f"Failed to list directory contents: {exc}", error_type="os_error", path=str(resolved))
    except Exception as exc:
        return _tool_error(f"Unexpected directory listing failure: {exc}", error_type="unexpected_error", path=str(resolved))


def _extract_command_root(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return ""
    match = re.match(r"^[\s(]*([A-Za-z0-9._:-]+)", stripped)
    return match.group(1).lower() if match else ""


def _is_readonly_command(command: str) -> bool:
    lowered = command.lower()
    blocked_fragments = (
        '>|',
        '2>',
        '>',
        '>>',
        '*>',
        'tee-object',
        'tee ',
        'out-file',
        'set-content',
        'add-content',
        'new-item',
        'set-item',
        'rename-item',
        'move-item',
        'copy-item',
        'remove-item',
        'mkdir ',
        'md ',
        'touch ',
        'rm ',
        'del ',
        'rmdir ',
        'git add',
        'git commit',
        'git apply',
        'git restore',
        'git push',
        'git checkout',
        'git switch',
        'git clean',
        'pip install',
        'npm install',
        'pnpm install',
        'python count_py_files.py',
        'open(',
        'write_text(',
        'write_bytes(',
        "'w'",
        '"w"',
        "'a'",
        '"a"',
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return False
    if any(re.search(pattern, lowered) for pattern in BLOCKED_COMMAND_PATTERNS):
        return False
    root = _extract_command_root(command)
    return bool(root) and root in READ_ONLY_COMMAND_ROOTS


def _resolve_command_workdir(arguments: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    raw_path = str(arguments.get("dir_path") or arguments.get("cwd") or ".").strip() or "."
    try:
        resolved = _resolve_directory_path(raw_path)
    except ValueError as exc:
        return None, _tool_error(str(exc), error_type="path_not_allowed", path=raw_path)
    except FileNotFoundError as exc:
        return None, _tool_error(str(exc), error_type="not_found", path=raw_path)
    except NotADirectoryError as exc:
        return None, _tool_error(str(exc), error_type="not_directory", path=raw_path)
    except OSError as exc:
        return None, _tool_error(f"Unable to access command working directory: {exc}", error_type="os_error", path=raw_path)
    except Exception as exc:
        return None, _tool_error(f"Unexpected command working directory failure: {exc}", error_type="unexpected_error", path=raw_path)
    return resolved, None


def _decode_output(data: bytes | str | None) -> tuple[str, str | None]:
    if data is None:
        return "", None
    if isinstance(data, str):
        return data.strip(), None
    try:
        return data.decode("utf-8").strip(), None
    except UnicodeDecodeError as exc:
        return data.decode("utf-8", errors="replace").strip(), str(exc)


def _build_command_runner(command: str) -> tuple[list[str], str]:
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-Command", command], "powershell"
    return ["/bin/bash", "-lc", command], "bash"


def _execute_run_command(arguments: dict[str, Any]) -> dict[str, Any]:
    command = str(arguments.get("command") or "").strip()
    timeout_s = _coerce_int(arguments.get("timeout_s"), default=DEFAULT_TOOL_TIMEOUT_SECONDS, minimum=1, maximum=600)
    if not command:
        return _tool_error("run_command requires a non-empty command.", error_type="missing_command")
    if not _is_readonly_command(command):
        return _tool_error(
            "run_command only allows read-only inspection commands. Use write_file for edits.",
            error_type="command_not_allowed",
            command=command,
        )

    cwd, cwd_error = _resolve_command_workdir(arguments)
    if cwd_error is not None:
        return {
            **cwd_error,
            "command": command,
            "timeout_s": timeout_s,
        }

    runner, shell_name = _build_command_runner(command)
    started_at = datetime.now(tz=timezone.utc)
    try:
        completed = subprocess.run(
            runner,
            cwd=cwd,
            capture_output=True,
            text=False,
            timeout=timeout_s,
            check=False,
        )
        stdout, stdout_decode_error = _decode_output(completed.stdout)
        stderr, stderr_decode_error = _decode_output(completed.stderr)
        decode_error = stdout_decode_error or stderr_decode_error
        result: dict[str, Any] = {
            "ok": completed.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": completed.returncode,
            "command": command,
            "resolved_cwd": str(cwd or WORKSPACE_ROOT),
            "timeout_s": timeout_s,
            "shell": shell_name,
            "started_at": started_at.isoformat(),
            "duration_ms": int((datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000),
        }
        if decode_error is not None:
            result["encoding_warning"] = decode_error
        return result
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_decode_error = _decode_output(exc.stdout)
        stderr, stderr_decode_error = _decode_output(exc.stderr)
        timeout_result = _tool_error(
            f"Command timed out after {timeout_s}s.",
            error_type="timeout",
            command=command,
            resolved_cwd=str(cwd or WORKSPACE_ROOT),
            timeout_s=timeout_s,
            shell=shell_name,
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000),
        )
        decode_error = stdout_decode_error or stderr_decode_error
        if decode_error is not None:
            timeout_result["encoding_warning"] = decode_error
        return timeout_result
    except UnicodeDecodeError as exc:
        return _tool_error(
            f"Command output could not be decoded as UTF-8: {exc}",
            error_type="decode_error",
            command=command,
            resolved_cwd=str(cwd or WORKSPACE_ROOT),
            timeout_s=timeout_s,
            shell=shell_name,
        )
    except OSError as exc:
        return _tool_error(
            f"Command could not be started: {exc}",
            error_type="os_error",
            command=command,
            resolved_cwd=str(cwd or WORKSPACE_ROOT),
            timeout_s=timeout_s,
            shell=shell_name,
        )
    except Exception as exc:
        return _tool_error(
            f"Unexpected command execution failure: {exc}",
            error_type="unexpected_error",
            command=command,
            resolved_cwd=str(cwd or WORKSPACE_ROOT),
            timeout_s=timeout_s,
            shell=shell_name,
        )


def _extract_permission_decision(message: AgentMessage) -> bool:
    decision = str(message.meta.get("decision") or message.content).strip().lower()
    return decision in {"y", "yes", "approved", "approve", "true"}


def _extract_permission_request_id(message: AgentMessage) -> str | None:
    request_id = message.meta.get("request_id")
    return str(request_id) if request_id else None


def apply_file_edit(path_hint: str | None, new_content: str, operation: str = "write") -> dict[str, Any]:
    target_path = _resolve_workspace_path(path_hint)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if operation == "append" and target_path.exists():
        written = target_path.read_text(encoding="utf-8") + new_content
    else:
        written = new_content
    target_path.write_text(written, encoding="utf-8")
    return {"path": str(target_path), "operation": operation, "bytes_written": len(written.encode("utf-8"))}


def _should_start_workflow(message: AgentMessage) -> bool:
    if message.msg_type != MessageType.THOUGHT:
        return False
    if str(message.sender).strip().lower() == "user":
        return True
    return str(message.meta.get("kind", "")) == "user_prompt"


def _is_permission_response(message: AgentMessage) -> bool:
    if message.msg_type == MessageType.PERMISSION_RESPONSE:
        return True
    return message.msg_type == MessageType.PERMISSION_REQUEST and str(message.meta.get("kind", "")) == "response"


async def route_message(client_id: str, message: AgentMessage) -> None:
    if _is_permission_response(message):
        request_id = _extract_permission_request_id(message)
        if not request_id:
            raise ValueError("Permission response is missing meta.request_id")
        decision = _extract_permission_decision(message)
        resolved = await permissions.resolve(request_id, decision)
        await manager.send_to(client_id, message)
        if not resolved:
            await _send_status(client_id, "brain", MessageType.THOUGHT, f"Received stale permission response for request {request_id}.", request_id=request_id, decision=decision)
        return

    if message.msg_type == MessageType.ASK_USER_RESPONSE:
        request_id = _extract_permission_request_id(message)
        if not request_id:
            raise ValueError("AskUser response is missing meta.request_id")
        answer = message.content
        resolved = await permissions.resolve(request_id, answer)
        await manager.send_to(client_id, message)
        if not resolved:
            await _send_status(client_id, "brain", MessageType.THOUGHT, f"Received stale response for ask_user {request_id}.", request_id=request_id)
        return

    await manager.send_to(client_id, message)
    if _should_start_workflow(message):
        task = asyncio.create_task(brain.handle_user_task(client_id, message), name=f"llm-task-{client_id}-{uuid4().hex[:8]}")
        await manager.register_task(client_id, task)

@app.on_event("shutdown")
async def _shutdown_llm_client() -> None:
    await llm_client.aclose()


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_id = websocket.query_params.get("client_id") or uuid4().hex
    await manager.connect(client_id, websocket)
    await _send_status(client_id, "brain", MessageType.THOUGHT, f"Client {client_id} connected.", event="connected")

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                parsed = AgentMessage.model_validate_json(raw_message)
            except ValidationError as exc:
                await _send_status(
                    client_id,
                    "brain",
                    MessageType.FINAL_ANSWER,
                    "Rejected malformed message. Expected the shared websocket schema.",

                    error=json.loads(exc.json()),
                    raw=raw_message,
                    status="validation_error",
                )
                continue

            try:
                await route_message(client_id, parsed)
            except Exception as exc:
                LOGGER.exception("Failed to route message for %s", client_id)
                await _send_status(
                    client_id,
                    "brain",
                    MessageType.FINAL_ANSWER,
                    "Server failed while processing the incoming message.",

                    error="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip(),
                    original_message=parsed.model_dump(),
                    status="server_error",
                )
    except WebSocketDisconnect:
        LOGGER.info("WebSocket disconnected: %s", client_id)
    finally:
        await brain.drop_conversation(client_id)
        await manager.disconnect(client_id)


def main() -> None:
    uvicorn.run("server:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()








