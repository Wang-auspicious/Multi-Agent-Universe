from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import websockets
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger("cli-monitor")
ANSI_RESET = "\x1b[0m"
ANSI_DIM = "\x1b[38;5;244m"
ANSI_USER = "\x1b[30;48;5;33m"
ANSI_AGENT = "\x1b[30;48;5;79m"
ANSI_SYSTEM = "\x1b[30;48;5;171m"
ANSI_THOUGHT = "\x1b[30;48;5;240m"
ANSI_WARNING = "\x1b[30;48;5;214m"
ANSI_CONNECTED = "\x1b[30;48;5;40m"
ANSI_CONNECTING = "\x1b[30;48;5;220m"
ANSI_DISCONNECTED = "\x1b[97;48;5;160m"

PERMISSION_OPTIONS = {
    "approve": "approved",
    "reject": "denied",
    "modify": "modify",
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
        self._local_echo_ids: set[str] = set()
        self._stream_buffers: dict[tuple[str, str, str, str, str], str] = {}
        self._open_stream_identity: tuple[str, str, str, str, str] | None = None
        self._printed_intro = False
        self._print_lock = asyncio.Lock()
        self._prompt_lock = asyncio.Lock()
        self._session = PromptSession[str](
            multiline=True,
            history=InMemoryHistory(),
            key_bindings=self._build_key_bindings(),
            bottom_toolbar=self._bottom_toolbar,
            prompt_continuation=self._prompt_continuation,
        )

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-s")
        def _submit(event) -> None:
            event.current_buffer.validate_and_handle()

        @kb.add("c-q")
        def _exit(event) -> None:
            asyncio.create_task(self._request_exit())

        @kb.add("c-l")
        def _clear(event) -> None:
            asyncio.create_task(self._clear_screen())

        @kb.add("c-p")
        def _history_previous(event) -> None:
            event.current_buffer.history_backward(count=1)

        @kb.add("c-n")
        def _history_next(event) -> None:
            event.current_buffer.history_forward(count=1)

        @kb.add("escape", "y", filter=Condition(lambda: self.pending_permission is not None))
        def _approve(event) -> None:
            asyncio.create_task(self._submit_permission_shortcut("approve"))

        @kb.add("escape", "n", filter=Condition(lambda: self.pending_permission is not None))
        def _reject(event) -> None:
            asyncio.create_task(self._submit_permission_shortcut("reject"))

        @kb.add("escape", "e", filter=Condition(lambda: self.pending_permission is not None))
        def _modify(event) -> None:
            asyncio.create_task(self._submit_permission_shortcut("modify"))

        return kb

    async def run(self) -> None:
        self._connection_task = asyncio.create_task(self._connection_supervisor(), name="cli-monitor-websocket")
        try:
            await self._print_intro_once()
            with patch_stdout(raw=True):
                while not self._shutdown.is_set():
                    try:
                        text = await self._session.prompt_async(self._prompt_message())
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
        await self._print_message("system", "thought", "Closing monitor and websocket session.")
        await self.shutdown()
        app = get_app()
        if app.is_running:
            app.exit(result="")

    async def _handle_user_input(self, text: str) -> None:
        self._remember_history(text)
        if text.startswith("/"):
            handled = await self._handle_local_command(text)
            if handled:
                return

        echo_id = uuid4().hex
        payload = {
            "sender": "user",
            "msg_type": "thought",
            "content": text,
            "meta": {
                "source": "cli_monitor",
                "client_id": self.client_id,
                "echo_id": echo_id,
            },
        }
        self.awaiting_agent_response = True
        self._local_echo_ids.add(echo_id)
        await self._print_message("user", "thought", text)
        if not self._enqueue_outgoing(payload):
            self.awaiting_agent_response = False
            self._local_echo_ids.discard(echo_id)
            await self._print_message(
                "system",
                "final_answer",
                "Cannot send message because the websocket is not connected.",
            )

    async def _handle_local_command(self, text: str) -> bool:
        command, _, remainder = text.partition(" ")
        command = command.lower()
        argument = remainder.strip()

        if command == "/clear":
            await self._clear_screen()
            return True
        if command in {"/exit", "/quit"}:
            await self._request_exit()
            return True
        if command == "/approve":
            await self._submit_permission_shortcut("approve")
            return True
        if command == "/reject":
            await self._submit_permission_shortcut("reject")
            return True
        if command == "/modify":
            await self._submit_permission_shortcut("modify", note=argument)
            return True
        return False

    async def _submit_permission_shortcut(self, decision: str, note: str = "") -> None:
        request = self.pending_permission
        request_id = self.current_permission_request_id
        if request is None or not request_id:
            await self._print_message("system", "thought", "No pending approval request.")
            return

        payload = self._build_permission_response_payload(request, decision, note=note)
        if not self._enqueue_outgoing(payload):
            await self._print_message(
                "system",
                "final_answer",
                f"Unable to send approval response for {request_id} because the websocket is disconnected.",
            )
            return

        suffix = f" ({note})" if note else ""
        await self._print_message(
            "user",
            "thought",
            f"{decision}{suffix}",
            meta={"request_id": request_id, "decision": payload['meta']['decision']},
        )
        self._complete_current_permission()

    def _build_permission_response_payload(
        self,
        request: PermissionRequestState,
        decision: str,
        *,
        note: str = "",
    ) -> dict[str, Any]:
        decision_key = PERMISSION_OPTIONS.get(decision, "denied")
        request_id = self.current_permission_request_id or request.request_id
        content = decision_key if not note else f"{decision_key}: {note}"
        return {
            "sender": "user",
            "msg_type": "permission_response",
            "content": content,
            "meta": {
                "kind": "response",
                "request_id": request_id,
                "decision": decision_key,
                "source_sender": request.sender,
                "note": note,
            },
        }

    async def _connection_supervisor(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                if self._shutdown.is_set():
                    break
                self.connection_state = "disconnected"
                self.connection_detail = "Retrying in 2.0s"
                await self._report_exception(
                    "WebSocket connection loop crashed",
                    exc,
                    extra=f"Reconnect target: {self.ws_url}",
                )
                await asyncio.sleep(2)

    async def _connect_once(self) -> None:
        self.connection_state = "connecting"
        self.connection_detail = self.ws_url

        try:
            async with websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=2**20,
            ) as websocket:
                self._websocket = websocket
                self.connection_state = "connected"
                self.connection_detail = "Connected"
                self._start_send_worker()
                await self._send_presence()
                await self._print_message(
                    "system",
                    "thought",
                    f"Connected to agent backend at {self.ws_url}.",
                )

                async for raw_message in websocket:
                    payload = self._safe_json_loads(raw_message)
                    if payload is None:
                        await self._print_message(
                            "system",
                            "final_answer",
                            f"Malformed JSON received: {raw_message[:400]}",
                        )
                        continue
                    await self._handle_payload(payload)
        finally:
            send_worker_task = self._send_worker_task
            self._websocket = None
            self._send_worker_task = None
            if send_worker_task is not None:
                send_worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await send_worker_task
            self.connection_state = "disconnected"
            self.connection_detail = "Socket closed"
            self.awaiting_agent_response = False

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        sender = self._coerce_text(payload.get("sender"), default="unknown")
        msg_type = self._coerce_text(payload.get("msg_type"), default="unknown")
        meta = self._coerce_meta(payload.get("meta"))
        content = self._coerce_text(payload.get("content"), default="")

        if sender == "user" and str(meta.get("client_id", "")) == self.client_id:
            echo_id = str(meta.get("echo_id", "")).strip()
            if echo_id and echo_id in self._local_echo_ids:
                self._local_echo_ids.discard(echo_id)
                return

        if sender not in {self.client_id, "user"}:
            self.active_agent = sender

        if meta.get("approval_policy"):
            self.permission_mode = str(meta["approval_policy"])
        elif self.pending_permission is not None:
            self.permission_mode = "approval-pending"
        else:
            self.permission_mode = "on-request"

        if msg_type == "final_answer":
            await self._handle_final_answer_payload(sender, content, meta)
            return

        if msg_type == "permission_request" and meta.get("kind") != "response":
            request = PermissionRequestState.from_payload(
                {
                    "sender": sender,
                    "msg_type": msg_type,
                    "content": content,
                    "meta": meta,
                }
            )
            if request is None:
                await self._print_message(
                    "system",
                    "final_answer",
                    "Permission request arrived without meta.request_id. Ignoring it.",
                )
                return
            self._permission_requests.append(request)
            if self.pending_permission is None:
                self._activate_next_permission_request()
            await self._print_permission_request(request)
            return

        if self._should_update_stream_message(msg_type, meta):
            await self._print_stream_message(sender, msg_type, content, meta)
            return

        await self._close_open_stream_if_needed()
        await self._print_message(sender, msg_type, content, meta=meta)

    async def _handle_final_answer_payload(self, sender: str, content: str, meta: dict[str, Any]) -> None:
        safe_content = content.strip() or "Task finished without a final text payload."
        run_id = str(meta.get("run_id") or "").strip()
        duplicate_stream = False

        if run_id:
            for identity, existing in list(self._stream_buffers.items()):
                if identity[2] != run_id:
                    continue
                if identity[3] == "output" and existing.strip() == safe_content.strip():
                    duplicate_stream = True
                del self._stream_buffers[identity]
                if self._open_stream_identity == identity:
                    await self._write("\n")
                    self._open_stream_identity = None

        if not duplicate_stream:
            await self._close_open_stream_if_needed()
            await self._print_message(sender, "final_answer", safe_content, meta=meta)

        self._reset_round_state()

    def _reset_round_state(self) -> None:
        self.awaiting_agent_response = False
        self._local_echo_ids.clear()
        if self.pending_permission is None:
            self.permission_mode = "on-request"

    def _activate_next_permission_request(self) -> None:
        if self.pending_permission is not None or not self._permission_requests:
            return
        self.pending_permission = self._permission_requests.popleft()
        self.current_permission_request_id = self.pending_permission.request_id
        self.permission_mode = "approval-pending"

    def _complete_current_permission(self) -> None:
        self.pending_permission = None
        self.current_permission_request_id = None
        if self._permission_requests:
            self._activate_next_permission_request()
        else:
            self.permission_mode = "on-request"

    def _start_send_worker(self) -> None:
        websocket = self._websocket
        if websocket is None:
            return
        if self._send_worker_task is not None and not self._send_worker_task.done():
            return
        self._send_worker_task = asyncio.create_task(self._send_worker(), name="cli-monitor-send-worker")

    async def _send_worker(self) -> None:
        while not self._shutdown.is_set():
            payload: dict[str, Any] | None = None
            try:
                payload = await self.send_queue.get()
                websocket = self._websocket
                if websocket is None:
                    self.send_queue.put_nowait(payload)
                    return
                await websocket.send(json.dumps(payload, ensure_ascii=False))
            except asyncio.CancelledError:
                if payload is not None:
                    self.send_queue.put_nowait(payload)
                raise
            except Exception as exc:
                if payload is not None:
                    self.send_queue.put_nowait(payload)
                self.connection_state = "disconnected"
                self.connection_detail = "Send failed"
                self.awaiting_agent_response = False
                await self._report_exception("send_worker failed", exc)
                websocket = self._websocket
                if websocket is not None:
                    with contextlib.suppress(Exception):
                        await websocket.close()
                return
            finally:
                if payload is not None:
                    self.send_queue.task_done()

    def _enqueue_outgoing(self, payload: dict[str, Any]) -> bool:
        if self._websocket is None or self.connection_state != "connected":
            return False
        self._start_send_worker()
        self.send_queue.put_nowait(payload)
        return True

    async def _send_presence(self) -> None:
        payload = {
            "sender": self.client_id,
            "msg_type": "thought",
            "content": "CLI monitor connected and listening to all agent traffic.",
            "meta": {"kind": "presence", "channel": "terminal_monitor"},
        }
        if not self._enqueue_outgoing(payload):
            await self._print_message(
                "system",
                "thought",
                "Presence message could not be queued because the websocket is not connected yet.",
            )

    async def _print_intro_once(self) -> None:
        if self._printed_intro:
            return
        self._printed_intro = True
        await self._print_message(
            "system",
            "thought",
            "CLI monitor booted in terminal-native mode. Stream chunks render as plain append-only text, final replies print as complete blocks, and the transcript stays in normal terminal scrollback for upward review.",
        )

    async def _print_permission_request(self, request: PermissionRequestState) -> None:
        await self._close_open_stream_if_needed()
        path = str(request.meta.get("path", "<unknown>"))
        operation = str(request.meta.get("operation", "unknown"))
        warning = request.meta.get("warning") or request.meta.get("risk") or request.meta.get("reason")
        lines = [
            self._format_header(request.created_at, request.sender, "approval", badge_style="warning"),
            f"request_id: {request.request_id}",
            f"operation : {operation}",
            f"path      : {path}",
            "actions   : Alt-Y approve  Alt-N reject  Alt-E modify  |  /approve /reject /modify <note>",
        ]
        if warning:
            lines.append(f"warning   : {warning}")
        if request.content.strip():
            lines.append(f"note      : {request.content.strip()}")
        await self._print_lines(lines)

    async def _print_stream_message(
        self,
        sender: str,
        msg_type: str,
        content: str,
        meta: dict[str, Any],
    ) -> None:
        identity = self._stream_identity(sender, msg_type, meta)
        if identity is None:
            await self._close_open_stream_if_needed()
            await self._print_message(sender, msg_type, content, meta=meta)
            return

        previous = self._stream_buffers.get(identity, "")
        merged = self._merge_stream_content(previous, content)
        if not merged:
            return

        if self._open_stream_identity and self._open_stream_identity != identity:
            await self._write("\n")
            self._open_stream_identity = None

        first_chunk = identity not in self._stream_buffers
        delta = merged[len(previous) :] if merged.startswith(previous) else merged
        self._stream_buffers[identity] = merged

        if first_chunk:
            header = self._format_header(
                datetime.now(),
                sender,
                self._stream_label(meta),
                badge_style="thought" if self._stream_bucket(meta) == "reasoning" else "agent",
            )
            await self._print_lines([header], trailing_newline=False)
            if merged:
                await self._write(f"{merged}")
        elif delta:
            await self._write(delta)

        self._open_stream_identity = identity
        if merged.endswith("\n"):
            self._open_stream_identity = None

    async def _close_open_stream_if_needed(self) -> None:
        if self._open_stream_identity is not None:
            await self._write("\n")
            self._open_stream_identity = None

    def _merge_stream_content(self, previous: str, content: str) -> str:
        if not content:
            return previous
        if content.startswith(previous):
            return content
        if previous.startswith(content):
            return previous
        return f"{previous}{content}"

    def _should_update_stream_message(self, msg_type: str, meta: dict[str, Any]) -> bool:
        run_id = str(meta.get("run_id") or "").strip()
        return msg_type == "thought" and bool(run_id) and self._stream_bucket(meta) is not None

    def _stream_bucket(self, meta: dict[str, Any]) -> str | None:
        stream_event = str(meta.get("stream_event") or "").strip()
        channel = str(meta.get("channel") or "").strip().lower()
        if stream_event in {"response.output_text.delta", "response.refusal.delta"}:
            return "output"
        if stream_event in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"} or channel == "reasoning":
            return "reasoning"
        return None

    def _stream_label(self, meta: dict[str, Any]) -> str:
        bucket = self._stream_bucket(meta)
        return "thinking" if bucket == "reasoning" else "stream"

    def _stream_identity(self, sender: str, msg_type: str, meta: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
        run_id = str(meta.get("run_id") or "").strip()
        bucket = self._stream_bucket(meta)
        stream_request_id = str(meta.get("stream_request_id") or "").strip() or "default"
        if msg_type != "thought" or not run_id or bucket is None:
            return None
        return sender, msg_type, run_id, bucket, stream_request_id

    async def _print_message(
        self,
        sender: str,
        msg_type: str,
        content: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> None:
        meta = meta or {}
        safe_content = content.rstrip() or "<empty>"
        lines = [self._format_header(datetime.now(), sender, self._header_label(msg_type, meta), badge_style=self._badge_style(sender, msg_type))]
        lines.extend(safe_content.splitlines() or [safe_content])
        await self._print_lines(lines)

    async def _print_lines(self, lines: list[str], *, trailing_newline: bool = True) -> None:
        text = "\n".join(lines)
        if trailing_newline:
            text += "\n\n"
        else:
            text += "\n"
        await self._write(text)

    async def _write(self, text: str) -> None:
        async with self._print_lock:
            print(text, end="", flush=True)

    async def _clear_screen(self) -> None:
        await self._write("\x1bc")

    async def _report_exception(self, context: str, exc: Exception, *, extra: str | None = None) -> None:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        diagnostic = context if not extra else f"{context}\n\n{extra}\n\n{trace}"
        if extra is None:
            diagnostic = f"{context}\n\n{trace}"
        LOGGER.exception("%s", context, exc_info=(type(exc), exc, exc.__traceback__))
        await self._close_open_stream_if_needed()
        await self._print_message("system", "final_answer", diagnostic)

    def _prompt_message(self) -> ANSI:
        if self.pending_permission is not None:
            prefix = f"{ANSI_WARNING}! {ANSI_RESET}"
        elif self.awaiting_agent_response:
            prefix = f"{ANSI_AGENT}> {ANSI_RESET}"
        else:
            prefix = f"{ANSI_USER}> {ANSI_RESET}"
        return ANSI(prefix)

    def _prompt_continuation(self, width: int, line_number: int, wrap_count: int) -> ANSI:
        return ANSI(f"{ANSI_DIM}| {ANSI_RESET}")

    def _bottom_toolbar(self) -> ANSI:
        state_style = {
            "connected": ANSI_CONNECTED,
            "connecting": ANSI_CONNECTING,
            "disconnected": ANSI_DISCONNECTED,
        }.get(self.connection_state, ANSI_DIM)
        state = f"{state_style} {self.connection_state.upper()} {ANSI_RESET}"
        agent = self.active_agent if self.active_agent != "idle" else "agent"
        if self.pending_permission is not None:
            detail = "Alt-Y approve  Alt-N reject  Alt-E modify  /approve /reject /modify"
        elif self.awaiting_agent_response:
            detail = f"{self._activity_summary()}  |  Ctrl-S send  Ctrl-Q quit"
        else:
            detail = "Ctrl-S send  Ctrl-L clear  Ctrl-Q quit  PgUp/PgDn terminal scroll"
        text = (
            f"{state}  {ANSI_DIM}agent {agent}{ANSI_RESET}  "
            f"{ANSI_DIM}mode {self.permission_mode}{ANSI_RESET}  {detail}"
        )
        return ANSI(text)

    def _activity_summary(self) -> str:
        if self.pending_permission is not None:
            operation = str(self.pending_permission.meta.get("operation", "operation"))
            path = str(self.pending_permission.meta.get("path", "<unknown>"))
            return f"approval needed: {operation} {path}"
        agent = self.active_agent if self.active_agent != "idle" else "agent"
        return f"{agent} is responding"

    def _header_label(self, msg_type: str, meta: dict[str, Any]) -> str:
        if msg_type == "final_answer":
            return "reply"
        if msg_type == "permission_request":
            return "approval"
        if msg_type != "thought":
            return msg_type.replace("_", " ")
        stage = str(meta.get("stage") or meta.get("status") or "").strip()
        if stage:
            return stage
        if meta.get("stream_event"):
            return "stream"
        return "thinking"

    def _badge_style(self, sender: str, msg_type: str) -> str:
        if sender in {self.client_id, "user"}:
            return "user"
        if sender == "system":
            return "system"
        if msg_type == "thought":
            return "thought"
        return "agent"

    def _format_header(self, created_at: datetime, sender: str, label: str, *, badge_style: str) -> str:
        badge_color = {
            "user": ANSI_USER,
            "agent": ANSI_AGENT,
            "system": ANSI_SYSTEM,
            "thought": ANSI_THOUGHT,
            "warning": ANSI_WARNING,
        }.get(badge_style, ANSI_THOUGHT)
        timestamp = f"{ANSI_DIM}{created_at.strftime('%H:%M:%S')}{ANSI_RESET}"
        badge = f"{badge_color} {sender} {ANSI_RESET}"
        meta = f"{ANSI_DIM} {label}{ANSI_RESET}"
        return f"{timestamp}  {badge}{meta}"

    def _remember_history(self, text: str) -> None:
        self._history_entries.append(text)

    @staticmethod
    def _safe_json_loads(raw: str) -> dict[str, Any] | None:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _coerce_text(value: Any, *, default: str = "") -> str:
        if value is None:
            return default
        try:
            return str(value)
        except Exception:
            return default

    @staticmethod
    def _coerce_meta(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}


async def main() -> None:
    monitor = CLIMonitor()
    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
