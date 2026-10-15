"""A scripted stand-in for the LLM, so the graph runs end to end with no API key.

It draws its conclusions from the demo scenario's facts. Diagnosis is unsure on the first pass when the scenario says
so, which exercises the loop back for more evidence.
"""
from __future__ import annotations

from triage.demo.scenarios import scenario_for
from triage.models import Alert, Diagnosis, Finding, FixProposal, Plan, Postmortem


class ScriptedReasoner:
    def plan(self, alert: Alert) -> Plan:
        return Plan(resource=scenario_for(alert.labels).resource)

    def diagnose(self, alert: Alert, findings: dict[str, Finding], round: int) -> Diagnosis:
        s = scenario_for(alert.labels)
        if s.first_confidence is not None and round == 1:
            return Diagnosis(cause="not yet clear", confidence=s.first_confidence, needs_more=True, reason=s.why_unsure)
        return Diagnosis(cause=s.cause, confidence=s.confidence)

    def propose_fix(self, alert: Alert, diagnosis: Diagnosis) -> FixProposal:
        s = scenario_for(alert.labels)
        return FixProposal(action=s.fix, risk=s.risk)

    def postmortem(self, alert: Alert, diagnosis: Diagnosis, proposal: FixProposal, outcome: str) -> Postmortem:
        s = scenario_for(alert.labels)
        summary = s.report if outcome == "fixed" else (
            f"Work item created with root cause, evidence and the rejected fix ({proposal.action}) for follow-up."
        )
        return Postmortem(title=f"{alert.title}: {diagnosis.cause}", summary=summary)
