"""Connectors that serve the demo incidents instead of calling Azure."""
from __future__ import annotations

from triage.demo.scenarios import scenario_for
from triage.models import ActionResult, Alert, Evidence, FixProposal, Postmortem, WorkItem


class DemoLogs:
    def query(self, alert: Alert, *, deeper: bool = False) -> Evidence:
        s = scenario_for(alert.labels)
        summary = s.logs_deeper if deeper and s.logs_deeper else s.logs
        return Evidence(source="logs", summary=summary, detail={"deeper": deeper})


class DemoMetrics:
    def query(self, alert: Alert) -> Evidence:
        return Evidence(source="metrics", summary=scenario_for(alert.labels).metrics)


class DemoChanges:
    def recent(self, alert: Alert) -> Evidence:
        return Evidence(source="change", summary=scenario_for(alert.labels).change)


class DemoActions:
    """Pretends to apply the fix. Records what it was asked to do so tests can check that nothing ran after a reject."""

    def __init__(self) -> None:
        self.applied: list[str] = []

    def apply(self, alert: Alert, proposal: FixProposal) -> ActionResult:
        self.applied.append(proposal.action)
        return ActionResult(ok=True, message=scenario_for(alert.labels).fix_result)


class DemoWorkItems:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create(self, alert: Alert, postmortem: Postmortem) -> WorkItem:
        self.created.append(postmortem.title)
        n = 1000 + len(self.created)
        return WorkItem(id=str(n), url=f"https://dev.azure.com/demo/triage/_workitems/edit/{n}")
