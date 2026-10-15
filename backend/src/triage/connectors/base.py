"""The only way agents reach the outside world.

Agents depend on these interfaces and never on Azure. One implementation talks to the demo data, another will talk
to Azure Monitor, the Activity Log, Azure DevOps and Azure Resource Manager. Reads are separate from the one
interface that can change something (ActionRunner), which the graph only reaches after a person approves.
"""
from __future__ import annotations

from typing import Protocol

from triage.models import ActionResult, Alert, Evidence, FixProposal, Postmortem, WorkItem


class LogSource(Protocol):
    def query(self, alert: Alert, *, deeper: bool = False) -> Evidence:
        """Find error patterns around the alert. `deeper` asks for a wider second pass."""


class MetricSource(Protocol):
    def query(self, alert: Alert) -> Evidence:
        """Find spikes and saturation around the alert."""


class ChangeSource(Protocol):
    def recent(self, alert: Alert) -> Evidence:
        """Find deploys, commits and config changes before the alert."""


class ActionRunner(Protocol):
    def apply(self, alert: Alert, proposal: FixProposal) -> ActionResult:
        """Apply an approved fix. The only interface that changes a resource."""


class WorkItemSink(Protocol):
    def create(self, alert: Alert, postmortem: Postmortem) -> WorkItem:
        """File the postmortem, for example as an Azure DevOps Boards work item."""
