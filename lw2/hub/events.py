"""In-process event bus: every component publishes what it does (frames on air, badge
state, chain transactions) and the UI receives it live over a WebSocket.

Events are telemetry for humans. Nothing here feeds a decision: the bridge decides only
from the badge signature and the contract decides only from what it can verify."""
from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections import deque


class EventBus:
    def __init__(self, keep: int = 600):
        self._log: deque[dict] = deque(maxlen=keep)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, type_: str, **data) -> dict:
        """Publish from any thread (radio callbacks, flow worker, HTTP handlers)."""
        with self._lock:
            ev = {"id": next(self._ids), "ts": time.time(), "type": type_, **data}
            self._log.append(ev)
        if self._loop is not None:
            for q in list(self._subs):
                self._loop.call_soon_threadsafe(_put_nowait, q, ev)
        return ev

    def recent(self, n: int = 200) -> list[dict]:
        with self._lock:
            return list(self._log)[-n:]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)


def _put_nowait(q: asyncio.Queue, ev: dict) -> None:
    try:
        q.put_nowait(ev)
    except asyncio.QueueFull:
        pass  # a stalled browser tab must never slow the radio down


BUS = EventBus()
