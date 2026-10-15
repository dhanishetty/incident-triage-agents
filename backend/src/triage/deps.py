"""Everything the agents depend on, gathered in one place so tests and the app can swap any of it."""
from __future__ import annotations

import os
from dataclasses import dataclass

from triage.connectors.base import ActionRunner, ChangeSource, LogSource, MetricSource, WorkItemSink
from triage.connectors.demo import DemoActions, DemoChanges, DemoLogs, DemoMetrics, DemoWorkItems
from triage.llm.base import Reasoner
from triage.llm.fake import ScriptedReasoner


@dataclass
class Deps:
    logs: LogSource
    metrics: MetricSource
    changes: ChangeSource
    actions: ActionRunner
    work_items: WorkItemSink
    reasoner: Reasoner
    max_rounds: int = 2  # how many times Diagnosis may ask for more evidence before it must decide


def demo_deps() -> Deps:
    return Deps(DemoLogs(), DemoMetrics(), DemoChanges(), DemoActions(), DemoWorkItems(), ScriptedReasoner())


def build_deps(mode: str | None = None) -> Deps:
    mode = mode or os.getenv("TRIAGE_MODE", "demo")
    if mode == "demo":
        return demo_deps()
    raise NotImplementedError(f"TRIAGE_MODE={mode!r} is not built yet. Only 'demo' works; Azure connectors are next.")
