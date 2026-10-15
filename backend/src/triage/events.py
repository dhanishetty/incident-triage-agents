"""The event stream a run produces.

The shape mirrors what the frontend's replay already plays (frontend/src/features/architecture/scenarios.ts):
a node changes status, some links carry a message, an agent says something, the run changes state. Node ids and
link keys are the diagram's ids, so the same view can replay a real run.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["node", "edges", "log", "run"]
NodeStatus = Literal["working", "done", "waiting", "failed"]
RunStatus = Literal["running", "awaiting_approval", "completed", "failed"]


class RunEvent(BaseModel):
    seq: int
    time: str
    kind: Kind
    node: str | None = None
    status: str | None = None  # a NodeStatus for "node" events, a RunStatus for "run" events
    chip: str | None = None
    edges: list[str] = Field(default_factory=list)  # "from-to" keys of the active links
    who: str | None = None
    text: str | None = None


class EventLog:
    """Append-only and thread-safe, because the evidence agents run in parallel."""

    def __init__(self) -> None:
        self._events: list[RunEvent] = []
        self._lock = threading.Lock()

    def add(self, **fields) -> RunEvent:
        with self._lock:
            event = RunEvent(seq=len(self._events) + 1, time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields)
            self._events.append(event)
            return event

    def after(self, seq: int = 0) -> list[RunEvent]:
        with self._lock:
            return self._events[seq:]


class Emitter:
    """What an agent uses to report progress. `delay` slows the demo down enough to watch."""

    def __init__(self, log: EventLog, delay: float = 0.0) -> None:
        self.log = log
        self.delay = delay

    def node(self, node: str, status: NodeStatus, chip: str | None = None) -> None:
        self.log.add(kind="node", node=node, status=status, chip=chip)
        if self.delay and status == "working":
            time.sleep(self.delay)

    def edges(self, *keys: str) -> None:
        self.log.add(kind="edges", edges=list(keys))

    def say(self, who: str, text: str) -> None:
        self.log.add(kind="log", who=who, text=text)

    def run(self, status: RunStatus) -> None:
        self.log.add(kind="run", status=status)
