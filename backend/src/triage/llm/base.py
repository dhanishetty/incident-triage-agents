"""The reasoning the agents delegate to an LLM.

Only the agents that need judgment are listed. The evidence agents mostly pass connector results through. The demo
uses a scripted implementation (llm/fake.py), so the whole graph runs with no API key. An Azure OpenAI
implementation will satisfy the same protocol.
"""
from __future__ import annotations

from typing import Protocol

from triage.models import Alert, Diagnosis, Finding, FixProposal, Plan, Postmortem


class Reasoner(Protocol):
    def plan(self, alert: Alert) -> Plan: ...

    def diagnose(self, alert: Alert, findings: dict[str, Finding], round: int) -> Diagnosis: ...

    def propose_fix(self, alert: Alert, diagnosis: Diagnosis) -> FixProposal: ...

    def postmortem(self, alert: Alert, diagnosis: Diagnosis, proposal: FixProposal, outcome: str) -> Postmortem: ...
