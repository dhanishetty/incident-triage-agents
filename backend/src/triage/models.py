"""The data that moves between connectors, agents and the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Alert(BaseModel):
    """An incoming alert, normalised from Azure Monitor's common alert schema."""

    id: str = "alert-1"
    title: str
    resource: str
    severity: Literal["low", "medium", "high", "critical"] = "high"
    labels: dict[str, str] = Field(default_factory=dict)


class Plan(BaseModel):
    """What the Triage supervisor decided to investigate."""

    resource: str
    agents: list[str] = Field(default_factory=lambda: ["logs", "metrics", "change"])


class Evidence(BaseModel):
    """Raw result from a connector, before an agent turns it into a finding."""

    source: Literal["logs", "metrics", "change"]
    summary: str
    detail: dict = Field(default_factory=dict)


class Finding(BaseModel):
    """What an evidence agent reports to Diagnosis."""

    agent: Literal["logs", "metrics", "change"]
    summary: str
    round: int = 1
    detail: dict = Field(default_factory=dict)  # structured signals behind the summary, for agents that reason over them


class Diagnosis(BaseModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    needs_more: bool = False
    reason: str = ""  # why Diagnosis is unsure, when it asks for more evidence
    kind: str = "unknown"  # bad-deploy, memory-leak, pool-size or unknown: lets Remediation pick a fix without parsing prose
    params: dict = Field(default_factory=dict)


class FixProposal(BaseModel):
    action: str
    risk: str
    kind: str = "none"  # rollback, restart, set_pool or none: what an Action connector should do
    params: dict = Field(default_factory=dict)


class ActionResult(BaseModel):
    ok: bool
    message: str


class Postmortem(BaseModel):
    title: str
    summary: str


class WorkItem(BaseModel):
    id: str
    url: str
