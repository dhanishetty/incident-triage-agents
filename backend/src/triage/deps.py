"""Everything the agents depend on, gathered in one place so tests and the app can swap any of it."""
from __future__ import annotations

import os
from dataclasses import dataclass

from triage.connectors.base import ActionRunner, ChangeSource, LogSource, MetricSource, WorkItemSink
from triage.connectors.demo import DemoActions, DemoChanges, DemoLogs, DemoMetrics, DemoWorkItems
from triage.connectors.env import EnvActions, EnvChanges, EnvLogs, EnvMetrics, ShopClient
from triage.llm.base import Reasoner
from triage.llm.fake import ScriptedReasoner
from triage.llm.rules import RuleReasoner


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


def env_deps(shop_url: str | None = None, verify_wait: float | None = None) -> Deps:
    """Connectors that read the demo environment (demo_env/shop), and a reasoner that diagnoses from what they find."""
    shop = ShopClient(shop_url or os.getenv("SHOP_URL", "http://shop:8100"))
    wait = verify_wait if verify_wait is not None else float(os.getenv("TRIAGE_VERIFY_WAIT", "6"))
    return Deps(EnvLogs(shop), EnvMetrics(shop), EnvChanges(shop), EnvActions(shop, wait), DemoWorkItems(), RuleReasoner())


def configured_env_deps() -> Deps | None:
    """TRIAGE_MODE=env turns on the environment connectors. Azure connectors will join as another mode."""
    mode = os.getenv("TRIAGE_MODE", "demo")
    if mode == "demo":
        return None
    if mode == "env":
        return env_deps()
    raise ValueError(f"TRIAGE_MODE={mode!r} is not built yet. Use 'demo' or 'env'; Azure connectors are next.")
