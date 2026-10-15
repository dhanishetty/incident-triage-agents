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


def azure_deps() -> Deps:
    """Read-only Azure connectors (Log Analytics and the Activity Log). Credentials come from DefaultAzureCredential:
    AZURE_CLIENT_ID, AZURE_TENANT_ID and AZURE_CLIENT_SECRET for a service principal, or a developer's `az login`."""
    from azure.identity import DefaultAzureCredential  # imported here so demo and env modes do not need the SDK
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.monitor.query import LogsQueryClient

    from triage.connectors.azure import AzureActionsNotWired, AzureChanges, AzureConfig, AzureLogs, AzureMetrics

    cfg = AzureConfig.from_env()
    credential = DefaultAzureCredential()
    logs = LogsQueryClient(credential)
    monitor = MonitorManagementClient(credential, cfg.subscription_id)
    return Deps(AzureLogs(logs, cfg), AzureMetrics(logs, cfg), AzureChanges(monitor, cfg), AzureActionsNotWired(), DemoWorkItems(), RuleReasoner())


def with_reasoner(deps: Deps) -> Deps:
    """TRIAGE_REASONER=rules (default) or openai: swap the judgment layer without touching the connectors."""
    which = os.getenv("TRIAGE_REASONER", "rules")
    if which == "openai":
        from triage.llm.azure_openai import from_env

        deps.reasoner = from_env()
    elif which != "rules":
        raise ValueError(f"TRIAGE_REASONER={which!r} is not known. Use 'rules' or 'openai'.")
    return deps


def configured_env_deps() -> Deps | None:
    """The graph for real alerts. TRIAGE_MODE=env reads the demo environment, TRIAGE_MODE=azure reads Azure."""
    mode = os.getenv("TRIAGE_MODE", "demo")
    if mode == "demo":
        return None
    if mode == "env":
        return with_reasoner(env_deps())
    if mode == "azure":
        return with_reasoner(azure_deps())
    raise ValueError(f"TRIAGE_MODE={mode!r} is not known. Use 'demo', 'env' or 'azure'.")
