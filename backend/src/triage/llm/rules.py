"""A rules-based reasoner: diagnoses from the evidence the connectors return, with no LLM.

It is the stand-in until an Azure OpenAI reasoner exists, and the baseline that reasoner will be scored against. Each
rule recognises one kind of incident from three kinds of signal (what the logs show, what the metrics show, what
changed) and adds confidence for every signal that agrees. When the signals do not yet agree enough it says so and
asks for a deeper look at the logs, which is what makes the loop back for more evidence happen for real.
"""
from __future__ import annotations

from triage.models import Alert, Diagnosis, Finding, FixProposal, Plan, Postmortem

ENOUGH = 0.8  # below this, and while a deeper pass is still possible, Diagnosis asks for more evidence


def _d(finding: Finding | None) -> dict:
    return finding.detail if finding else {}


class RuleReasoner:
    def plan(self, alert: Alert) -> Plan:
        return Plan(resource=alert.resource)

    def diagnose(self, alert: Alert, findings: dict[str, Finding], round: int) -> Diagnosis:
        logs, metrics, change = _d(findings.get("logs")), _d(findings.get("metrics")), _d(findings.get("change"))
        deeper = bool(logs.get("deeper"))
        sigs = logs.get("signatures", [])
        top = sigs[0]["msg"] if sigs else ""
        changes = change.get("changes", [])
        deploys = [c for c in changes if c["kind"] == "deploy" and not c["meta"].get("rollback")]
        error_rate = metrics.get("error_rate_now") or 0.0

        if "OOMKilled" in top or (metrics.get("restarts_last_minute", 0) >= 2 and metrics.get("mem_slope_mb_per_min", 0) > 20):
            conf = 0.30 if "OOMKilled" in top else 0.10
            conf += 0.25 if metrics.get("mem_slope_mb_per_min", 0) > 20 else 0.0
            conf += 0.20 if not changes else 0.0
            conf += 0.10 if metrics.get("restarts_last_minute", 0) >= 2 else 0.0
            return self._result(
                "a memory leak in the running build: the container keeps being killed for exceeding its memory limit, and nothing was deployed or changed",
                conf, deeper, "The kills fit a leak, but something may have changed recently.", "memory-leak", {},
            )

        if "Timeout waiting for a database connection" in top or ((metrics.get("db_util") or 0) >= 0.9 and error_rate >= 0.03):
            cut = next((c for c in changes if c["meta"].get("setting") == "pool_size" and c["meta"].get("to", 0) < c["meta"].get("from_", 0)), None)
            conf = 0.30 if "Timeout waiting" in top else 0.10
            conf += 0.20 if (metrics.get("db_util") or 0) >= 0.9 else 0.0
            conf += 0.20 if cut else 0.0
            conf += 0.15 if logs.get("pool_saturated") else 0.0
            frm, to = (cut["meta"]["from_"], cut["meta"]["to"]) if cut else (8, None)
            cause = f"the database connection pool was cut from {frm} to {to} and now runs out under normal traffic" if cut else "the database connection pool is exhausted"
            return self._result(cause, conf, deeper, "The pool change fits, but it is not yet clear the pool itself is the bottleneck.", "pool-size", {"from": frm, "to": to})

        if "Error" in top and error_rate >= 0.03:
            recent = [c for c in deploys if c["age_min"] <= 180]
            where = top.split(": ", 1)[0]
            conf = 0.30 + (0.20 if error_rate >= 0.03 else 0.0) + (0.20 if recent else 0.0) + (0.15 if logs.get("frames") else 0.0)
            deploy = recent[0] if recent else None
            version = deploy["meta"].get("version") if deploy else None
            cause = f"deploy {version} introduced {where}" if version else f"an application bug: {where}"
            return self._result(
                cause, conf, deeper, "The errors start right after a deploy, but the log lines do not yet say which code changed.", "bad-deploy",
                {"bad_version": version, "rollback_to": deploy["meta"].get("from_version") if deploy else None},
            )

        return Diagnosis(cause="not yet clear", confidence=0.2, needs_more=not deeper, reason="The logs, metrics and changes do not point at one cause yet.", kind="unknown")

    @staticmethod
    def _result(cause: str, conf: float, deeper: bool, unsure: str, kind: str, params: dict) -> Diagnosis:
        conf = round(min(conf, 0.95), 2)
        needs_more = conf < ENOUGH and not deeper
        return Diagnosis(cause=cause, confidence=conf, needs_more=needs_more, reason=unsure if needs_more else "", kind=kind, params=params)

    def propose_fix(self, alert: Alert, diagnosis: Diagnosis) -> FixProposal:
        p = diagnosis.params
        if diagnosis.kind == "bad-deploy" and p.get("rollback_to"):
            return FixProposal(action=f"roll shop-api back to {p['rollback_to']}", risk=f"low, {p['rollback_to']} was running cleanly before {p['bad_version']}", kind="rollback", params={"to": p["rollback_to"]})
        if diagnosis.kind == "memory-leak":
            return FixProposal(
                action="restart shop-api and raise its memory limit to 2048 MB as a stopgap",
                risk="medium, a restart briefly interrupts orders and the leak itself is still in the build",
                kind="restart", params={"limit_mb": 2048},
            )
        if diagnosis.kind == "pool-size" and p.get("to") is not None:
            return FixProposal(action=f"set the database pool size back to {p['from']}", risk="low, it restores the previous setting", kind="set_pool", params={"size": p["from"]})
        return FixProposal(action="escalate to the on-call engineer: no safe automatic fix", risk="none", kind="none")

    def postmortem(self, alert: Alert, diagnosis: Diagnosis, proposal: FixProposal, outcome: str) -> Postmortem:
        follow_up = {
            "bad-deploy": "add a test for orders that have no coupon",
            "memory-leak": "profile the heap to find the leak",
            "pool-size": "load-test pool settings before changing them",
        }.get(diagnosis.kind, "investigate further")
        applied = {
            "fixed": f"Applied: {proposal.action}.",
            "unhealthy": f"Applied: {proposal.action}, but the system did not recover. Needs follow-up.",
        }.get(outcome, f"Not applied: {proposal.action}.")
        return Postmortem(
            title=f"{alert.title}: {diagnosis.cause}",
            summary=f"Work item created: {diagnosis.cause} (confidence {diagnosis.confidence:.0%}). {applied} Follow-up: {follow_up}.",
        )
