from __future__ import annotations

from collections.abc import Callable

from agent_os.core.events import Event


class EventBus:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subs: list[Callable[[Event], None]] = []

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subs.append(callback)

    def publish(self, event: Event) -> None:
        self._events.append(event)
        for sub in self._subs:
            sub(event)
