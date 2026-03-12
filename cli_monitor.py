from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import websockets
from prompt_toolkit import PromptSession, HTML
from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger("cli-monitor")
ANSI_RESET = "\x1b[0m"
ANSI_DIM = "\x1b[38;5;244m"
ANSI_USER = "\x1b[38;5;33m"
ANSI_AGENT = "\x1b[38;5;79m"
ANSI_SYSTEM = "\x1b[38;5;171m"
ANSI_THOUGHT = "\x1b[38;5;240m"
ANSI_WARNING = "\x1b[30;48;5;214m"
ANSI_CONNECTED = "\x1b[32m"
ANSI_CONNECTING = "\x1b[33m"
ANSI_DISCONNECTED = "\x1b[31m"

ANSI_FG_GREEN = "\x1b[32m"
ANSI_FG_RED = "\x1b[31m"
ANSI_FG_CYAN = "\x1b[36m"
ANSI_FG_YELLOW = "\x1b[33m"
ANSI_FG_WHITE = "\x1b[97m"
ANSI_LINE = "─"

PERMISSION_OPTIONS_KEYS = ["approve", "reject", "modify"]
PERMISSION_LABELS = {
    "approve": "Approve",
    "reject": "Reject",
    "modify": "Modify (Experimental)",
}


@dataclass
class PermissionRequestState:
    request_id: str
    sender: str
    content: str
    meta: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PermissionRequestState | None":
        meta = payload.get("meta", {})
        request_id = str(meta.get("request_id", "")).strip()
        if not request_id:
            return None
        return cls(
            request_id=request_id,
            sender=str(payload.get("sender", "unknown")),
            content=str(payload.get("content", "")),
            meta=dict(meta),
        )


class CLIMonitor:
    def __init__(self, ws_url: str = "ws://127.0.0.1:8765/ws") -> None:
        self.client_id = f"cli-monitor-{uuid4().hex[:8]}"
        self.ws_url = f"{ws_url}?client_id={self.client_id}"
        self.connection_state = "connecting"
        self.connection_detail = "Waiting for websocket"
        self.active_agent = "idle"
        self.permission_mode = "on-request"
        self.awaiting_agent_response = False
        self._shutdown = asyncio.Event()
        self._websocket: Any | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._send_worker_task: asyncio.Task[None] | None = None
        self.send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._history_entries: list[str] = []
        self._permission_requests: deque[PermissionRequestState] = deque()
        self.pending_permission: PermissionRequestState | None = None
        self.current_permission_request_id: str | None = None
        self._permission_menu_idx = 0
        self._local_echo_ids: set[str] = set()
        self._stream_buffers: dict[tuple[str, str, str, str, str], str] = {}
        self._open_stream_identity: tuple[str, str, str, str, str] | None = None
        self._printed_intro = False
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_idx = 0
        self._last_is_dynamic = False
        self._print_lock = asyncio.Lock()
        self._prompt_lock = asyncio.Lock()
        
        self._session = PromptSession[str](
            multiline=True,
            history=InMemoryHistory(),
            key_bindings=self._build_key_bindings(),
            bottom_toolbar=self._bottom_toolbar,
            prompt_continuation=self._prompt_continuation,
            style=Style.from_dict({
                "bottom-toolbar": "noinherit",
            })
        )

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-s")
        def _submit(event) -> None:
            if self.pending_permission is None:
                event.current_buffer.validate_and_handle()

        @kb.add("c-q")
        def _exit(event) -> None:
            asyncio.create_task(self._request_exit())

        @kb.add("c-l")
        def _clear(event) -> None:
            asyncio.create_task(self._clear_screen())

        @kb.add("up", filter=Condition(lambda: self.pending_permission is not None))
        def _menu_up(event) -> None:
            self._permission_menu_idx = (self._permission_menu_idx - 1) % len(PERMISSION_OPTIONS_KEYS)

        @kb.add("down", filter=Condition(lambda: self.pending_permission is not None))
        def _menu_down(event) -> None:
            self._permission_menu_idx = (self._permission_menu_idx + 1) % len(PERMISSION_OPTIONS_KEYS)

        @kb.add("enter", filter=Condition(lambda: self.pending_permission is not None))
        def _menu_confirm(event) -> None:
            decision = PERMISSION_OPTIONS_KEYS[self._permission_menu_idx]
            asyncio.create_task(self._submit_permission_shortcut(decision))

        @kb.add("escape", "y", filter=Condition(lambda: self.pending_permission is not None))
        def _approve(event) -> None:
            asyncio.create_task(self._submit_permission_shortcut("approve"))

        @kb.add("escape", "n", filter=Condition(lambda: self.pending_permission is not None))
        def _reject(event) -> None:
            asyncio.create_task(self._submit_permission_shortcut("reject"))

        return kb

    async def run(self) -> None:
        self._connection_task = asyncio.create_task(self._connection_supervisor(), name="cli-monitor-websocket")
        try:
            await self._print_intro_once()
            with patch_stdout(raw=True):
                while not self._shutdown.is_set():
                    try:
                        placeholder_html = HTML('<style color="#666666">Type your message or @path/to/file</style>')
                        text = await self._session.prompt_async(
                            self._prompt_header,
                            placeholder=placeholder_html
                        )
                    except (EOFError, KeyboardInterrupt):
                        await self._request_exit()
                        break

                    text = text.strip()
                    if not text:
                        continue
                    await self._handle_user_input(text)
        finally:
            await self.shutdown()
            if self._connection_task is not None:
                self._connection_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._connection_task

    async def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            with contextlib.suppress(Exception):
                await websocket.close()

    async def _request_exit(self) -> None:
        await self._print_message("system", "thought", "Closing monitor.")
        await self.shutdown()
        app = get_app()
        if app.is_running:
            app.exit(result="")

    async def _handle_user_input(self, text: str) -> None:
        self._remember_history(text)
        if text.startswith("/"):
            handled = await self._handle_local_command(text)
            if handled: return

        echo_id = uuid4().hex
        payload = {
            "sender": "user",
            "msg_type": "thought",
            "content": text,
            "meta": {"source": "cli_monitor", "client_id": self.client_id, "echo_id": echo_id},
        }
        self.awaiting_agent_response = True
        self._local_echo_ids.add(echo_id)
        await self._print_message("user", "thought", text)
        if not self._enqueue_outgoing(payload):
            self.awaiting_agent_response = False
            self._local_echo_ids.discard(echo_id)
            await self._print_message("system", "final_answer", "Websocket disconnected.")

    def _remember_history(self, text: str) -> None:
        self._history_entries.append(text)

    async def _handle_local_command(self, text: str) -> bool:
        command, _, remainder = text.partition(" ")
        command = command.lower()
        if command == "/clear": await self._clear_screen(); return True
        if command in {"/exit", "/quit"}: await self._request_exit(); return True
        if command == "/approve": await self._submit_permission_shortcut("approve"); return True
        if command == "/reject": await self._submit_permission_shortcut("reject"); return True
        return False

    async def _submit_permission_shortcut(self, decision: str, note: str = "") -> None:
        request = self.pending_permission
        request_id = self.current_permission_request_id
        if request is None or not request_id: return

        decision_key = {"approve": "approved", "reject": "denied", "modify": "modify"}.get(decision, "denied")
        payload = {
            "sender": "user",
            "msg_type": "permission_response",
            "content": decision_key,
            "meta": {
                "kind": "response",
                "request_id": request_id,
                "decision": decision_key,
                "source_sender": request.sender,
                "note": note,
            },
        }
        
        if self._enqueue_outgoing(payload):
            await self._print_message("user", "thought", f"{decision} for {request_id}")
            self._complete_current_permission()
        else:
            await self._print_message("system", "final_answer", "Failed to send approval.")

    async def _connection_supervisor(self) -> None:
        while not self._shutdown.is_set():
            try: await self._connect_once()
            except asyncio.CancelledError: raise
            except Exception:
                self.connection_state = "disconnected"
                await asyncio.sleep(2)

    async def _connect_once(self) -> None:
        self.connection_state = "connecting"
        try:
            async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as websocket:
                self._websocket = websocket
                self.connection_state = "connected"
                self._start_send_worker()
                await self._send_presence()
                async for raw_message in websocket:
                    payload = self._safe_json_loads(raw_message)
                    if payload: await self._handle_payload(payload)
        finally:
            self._websocket = None
            self.connection_state = "disconnected"
            self.awaiting_agent_response = False

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        sender = self._coerce_text(payload.get("sender"), default="unknown")
        msg_type = self._coerce_text(payload.get("msg_type"), default="unknown")
        meta = self._coerce_meta(payload.get("meta"))
        content = self._coerce_text(payload.get("content"), default="")

        if sender == "user" and meta.get("client_id") == self.client_id:
            if meta.get("echo_id") in self._local_echo_ids:
                self._local_echo_ids.discard(meta["echo_id"])
                return

        if sender not in {self.client_id, "user"}: self.active_agent = sender

        if msg_type == "final_answer":
            await self._handle_final_answer_payload(sender, content, meta)
            return

        if msg_type == "permission_request" and meta.get("kind") != "response":
            request = PermissionRequestState.from_payload(payload)
            if request:
                self._permission_requests.append(request)
                if self.pending_permission is None: self._activate_next_permission_request()
                get_app().invalidate()
            return

        if self._should_update_stream_message(msg_type, meta):
            await self._print_stream_message(sender, msg_type, content, meta)
            return

        await self._close_open_stream_if_needed()
        await self._print_message(sender, msg_type, content, meta=meta)

    async def _handle_final_answer_payload(self, sender: str, content: str, meta: dict[str, Any]) -> None:
        await self._close_open_stream_if_needed()
        await self._print_message(sender, "final_answer", content, meta=meta)
        self.awaiting_agent_response = False
        self._local_echo_ids.clear()

    def _activate_next_permission_request(self) -> None:
        if self._permission_requests:
            self.pending_permission = self._permission_requests.popleft()
            self.current_permission_request_id = self.pending_permission.request_id
            self.permission_mode = "approval-pending"
            self._permission_menu_idx = 0

    def _complete_current_permission(self) -> None:
        self.pending_permission = None
        self.current_permission_request_id = None
        if self._permission_requests: self._activate_next_permission_request()
        else: self.permission_mode = "on-request"

    def _start_send_worker(self) -> None:
        if self._websocket and (not self._send_worker_task or self._send_worker_task.done()):
            self._send_worker_task = asyncio.create_task(self._send_worker())

    async def _send_worker(self) -> None:
        while not self._shutdown.is_set():
            payload = await self.send_queue.get()
            try:
                if self._websocket: await self._websocket.send(json.dumps(payload))
            except Exception: pass
            finally: self.send_queue.task_done()

    def _enqueue_outgoing(self, payload: dict[str, Any]) -> bool:
        if self._websocket and self.connection_state == "connected":
            self.send_queue.put_nowait(payload)
            return True
        return False

    async def _send_presence(self) -> None:
        self._enqueue_outgoing({"sender": self.client_id, "msg_type": "thought", "content": "connected", "meta": {"kind": "presence"}})

    async def _print_intro_once(self) -> None:
        if not self._printed_intro:
            self._printed_intro = True
            await self._print_message("system", "thought", "Gemini Composer CLI Activated.")

    async def _print_stream_message(self, sender: str, msg_type: str, content: str, meta: dict[str, Any]) -> None:
        identity = self._stream_identity(sender, msg_type, meta)
        if not identity: return
        
        previous = self._stream_buffers.get(identity, "")
        merged = self._merge_stream_content(previous, content)
        self._stream_buffers[identity] = merged

        if self._stream_bucket(meta) == "reasoning":
            header = self._format_header(datetime.now(), sender, "thinking", badge_style="thought", spinner=True)
            preview = merged.replace("\n", " ").strip()[-60:]
            await self._write(f"\r\x1b[K{header} {ANSI_DIM}{preview}{ANSI_RESET}")
            self._last_is_dynamic = True
        else:
            if self._last_is_dynamic: await self._write("\n"); self._last_is_dynamic = False
            delta = merged[len(previous) :] if merged.startswith(previous) else merged
            if identity not in self._stream_buffers:
                await self._print_lines([self._format_header(datetime.now(), sender, "stream", badge_style="agent")], False)
            if delta: await self._write(delta)
        self._open_stream_identity = identity

    async def _close_open_stream_if_needed(self) -> None:
        if self._open_stream_identity:
            await self._write("\n")
            self._open_stream_identity = None
            self._last_is_dynamic = False

    def _merge_stream_content(self, previous: str, content: str) -> str:
        return content if content.startswith(previous) else f"{previous}{content}"

    def _should_update_stream_message(self, msg_type: str, meta: dict[str, Any]) -> bool:
        return msg_type in {"thought", "content"} and bool(meta.get("run_id")) and self._stream_bucket(meta) is not None

    def _stream_bucket(self, meta: dict[str, Any]) -> str | None:
        evt, chan = str(meta.get("stream_event", "")), str(meta.get("channel", "")).lower()
        if "output" in evt or chan == "output": return "output"
        if "reasoning" in evt or chan == "reasoning": return "reasoning"
        return None

    def _stream_identity(self, sender: str, msg_type: str, meta: dict[str, Any]) -> tuple | None:
        run_id, bucket = meta.get("run_id"), self._stream_bucket(meta)
        if not run_id or not bucket: return None
        return sender, msg_type, run_id, bucket

    async def _print_message(self, sender: str, msg_type: str, content: str, *, meta: dict[str, Any] | None = None) -> None:
        if self._last_is_dynamic: await self._write("\n"); self._last_is_dynamic = False
        lines = [self._format_header(datetime.now(), sender, self._header_label(msg_type, meta or {}), badge_style=self._badge_style(sender, msg_type))]
        lines.extend(self._format_rich_content(content.rstrip()))
        await self._print_lines(lines)

    def _format_rich_content(self, content: str) -> list[str]:
        formatted, in_shell = [], False
        for line in content.splitlines():
            if "```shell" in line or "```bash" in line:
                in_shell = True
                formatted.append(f"{ANSI_DIM}╭─ Shell Command {'─' * 40}{ANSI_RESET}")
                continue
            elif in_shell and line.startswith("```"):
                in_shell = False
                formatted.append(f"{ANSI_DIM}╰─{'─' * 56}{ANSI_RESET}")
                continue
            if in_shell: formatted.append(f"{ANSI_DIM}│{ANSI_RESET} {line}"); continue
            s = line.lstrip()
            if s.startswith("+") and not s.startswith("+++"): formatted.append(f"{ANSI_FG_GREEN}{line}{ANSI_RESET}")
            elif s.startswith("-") and not s.startswith("---"): formatted.append(f"{ANSI_FG_RED}{line}{ANSI_RESET}")
            elif "@@" in s or ("Edit " in s and "=>" in s): formatted.append(f"{ANSI_FG_CYAN}{line}{ANSI_RESET}")
            else: formatted.append(line)
        return formatted

    async def _write(self, text: str) -> None:
        async with self._print_lock: print(text, end="", flush=True)

    async def _print_lines(self, lines: list[str], trailing: bool = True) -> None:
        await self._write("\n".join(lines) + ("\n\n" if trailing else "\n"))

    def _prompt_header(self) -> ANSI:
        prefix = ""
        if self.pending_permission:
            p = self.pending_permission
            path = p.meta.get("path", "unknown")
            op = p.meta.get("operation", "edit")
            card = [
                f"{ANSI_FG_CYAN}╭─ Permission Requested {'─' * 60}{ANSI_RESET}",
                f"{ANSI_FG_CYAN}│{ANSI_RESET} Action: {ANSI_FG_YELLOW}{op}{ANSI_RESET} on {ANSI_FG_WHITE}{path}{ANSI_RESET}",
                f"{ANSI_FG_CYAN}│{ANSI_RESET} Why: {p.content.strip() or 'No reason provided.'}",
                f"{ANSI_FG_CYAN}│{ANSI_RESET}",
            ]
            for i, key in enumerate(PERMISSION_OPTIONS_KEYS):
                label = PERMISSION_LABELS[key]
                if i == self._permission_menu_idx:
                    card.append(f"{ANSI_FG_CYAN}│{ANSI_RESET}  {ANSI_FG_GREEN}● {label} (Enter to confirm){ANSI_RESET}")
                else:
                    card.append(f"{ANSI_FG_CYAN}│{ANSI_RESET}    {ANSI_DIM}{label}{ANSI_RESET}")
            card.append(f"{ANSI_FG_CYAN}╰─{'─' * 81}{ANSI_RESET}")
            prefix = "\n" + "\n".join(card) + "\n"

        line = f"{ANSI_DIM}{ANSI_LINE * 100}{ANSI_RESET}"
        header = f"{ANSI_DIM}auto-accept edits  shift+tab to plan  2 GEMINI.md files{ANSI_RESET}"
        return ANSI(f"{prefix}\n {header}\n{line}\n {ANSI_USER}> ")

    def _prompt_continuation(self, width: int, line_number: int, wrap_count: int) -> ANSI:
        return ANSI(f"{ANSI_DIM}│ {ANSI_RESET}")

    def _bottom_toolbar(self) -> ANSI:
        cwd = os.getcwd().replace(os.path.expanduser("~"), "~")
        branch = "main"
        with contextlib.suppress(Exception):
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        status = "no sandbox (see /docs)"
        model = f"/model Auto ({self.active_agent})"
        line = f"{ANSI_DIM}{ANSI_LINE * 100}{ANSI_RESET}"
        return ANSI(f"{line}\n {ANSI_DIM}{cwd} ({branch}){ANSI_RESET} ".ljust(60) + f"{ANSI_DIM}{status}{ANSI_RESET} ".center(30) + f"{ANSI_DIM}{model}{ANSI_RESET} ".rjust(40))

    def _header_label(self, msg_type: str, meta: dict) -> str:
        return "reply" if msg_type == "final_answer" else str(meta.get("stage") or "thinking")

    def _badge_style(self, sender: str, msg_type: str) -> str:
        return "user" if sender in {self.client_id, "user"} else "agent"

    def _format_header(self, t: datetime, sender: str, label: str, *, badge_style: str, spinner: bool = False) -> str:
        spin = f"{ANSI_FG_CYAN}{self._spinner_chars[self._spinner_idx % len(self._spinner_chars)]} {ANSI_RESET}" if spinner else ""
        self._spinner_idx += 1
        color = {"user": ANSI_USER, "agent": ANSI_AGENT, "warning": ANSI_WARNING}.get(badge_style, ANSI_THOUGHT)
        return f"{spin}{ANSI_DIM}{t.strftime('%H:%M:%S')}  {color} {sender} {ANSI_RESET} {ANSI_DIM}{label}{ANSI_RESET}"

    @staticmethod
    def _safe_json_loads(raw: str) -> dict | None:
        try: return json.loads(raw)
        except Exception: return None

    @staticmethod
    def _coerce_text(v, default="") -> str:
        return str(v) if v is not None else default

    @staticmethod
    def _coerce_meta(v) -> dict:
        return dict(v) if isinstance(v, dict) else {}

if __name__ == "__main__":
    try: asyncio.run(CLIMonitor().run())
    except KeyboardInterrupt: pass
