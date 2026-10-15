"""Starts runs, keeps their events, and resumes them when a person decides.

A run executes the graph in a background thread. At the approval gate the graph pauses (LangGraph interrupt) and the
thread ends; approving or rejecting starts a new thread that resumes from the checkpoint.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from langgraph.types import Command

from triage.events import Emitter, EventLog, RunStatus
from triage.models import Alert


@dataclass
class Run:
    id: str
    alert: Alert
    events: EventLog
    config: dict
    graph: object
    status: RunStatus = "running"
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class NotAwaitingApproval(Exception):
    pass


class RunManager:
    def __init__(self, graph, step_delay: float = 0.0, env_graph=None) -> None:
        self.graph = graph  # demo data and the scripted reasoner
        self.env_graph = env_graph  # the demo environment's connectors and the rules-based reasoner
        self.step_delay = step_delay
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        return list(self._runs.values())

    def start(self, alert: Alert) -> Run:
        run_id = uuid.uuid4().hex[:8]
        events = EventLog()
        config = {"configurable": {"thread_id": run_id, "emitter": Emitter(events, self.step_delay)}}
        # An alert that names a demo scenario replays that scenario. Any other alert is investigated for real.
        graph = self.env_graph if self.env_graph is not None and "demo_scenario" not in alert.labels else self.graph
        run = Run(id=run_id, alert=alert, events=events, config=config, graph=graph)
        self._runs[run_id] = run
        self._spawn(run, {"alert": alert.model_dump()})
        return run

    def decide(self, run_id: str, decision: str) -> Run:
        run = self._runs[run_id]
        with run.lock:
            if run.status != "awaiting_approval":
                raise NotAwaitingApproval(f"Run {run_id} is {run.status}, not waiting for approval.")
            run.status = "running"
        self._spawn(run, Command(resume=decision))
        return run

    def _spawn(self, run: Run, payload) -> None:
        threading.Thread(target=self._execute, args=(run, payload), daemon=True, name=f"run-{run.id}").start()

    def _execute(self, run: Run, payload) -> None:
        try:
            run.graph.invoke(payload, run.config)
            paused = bool(run.graph.get_state(run.config).next)  # still has a node to run: stopped at the gate
            run.status = "awaiting_approval" if paused else "completed"
        except Exception as exc:  # a failed run must still end its event stream
            run.error = f"{type(exc).__name__}: {exc}"
            run.status = "failed"
            run.events.add(kind="log", who="Triage API", text=f"Run failed: {run.error}")
            run.events.add(kind="run", status="failed")
