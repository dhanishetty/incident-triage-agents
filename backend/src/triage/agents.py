"""The eight agents, as graph nodes.

Each node does its job through `deps` (connectors and the reasoner) and reports progress through the run's emitter.
Node ids and link keys match the frontend diagram (frontend/src/features/architecture/diagrams.ts).

State holds plain dicts (model_dump) so checkpoints serialise cleanly; nodes rebuild the models they need.
"""
from __future__ import annotations

from typing import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from triage.deps import Deps
from triage.events import Emitter
from triage.models import Alert, Diagnosis, Evidence, Finding, FixProposal


def _em(config: RunnableConfig) -> Emitter:
    return config["configurable"]["emitter"]


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def make_nodes(deps: Deps) -> dict[str, Callable]:
    def triage(state: dict, config: RunnableConfig) -> dict:
        em, alert = _em(config), Alert(**state["alert"])
        em.node("alert", "working", "firing")
        em.node("api", "working", "receiving")
        em.edges("alert-api")
        em.say("Azure Monitor", f"Alert fired: {alert.title}")
        em.say("Triage API", "Run created. Starting the agent graph.")
        em.node("alert", "done")
        em.node("api", "done")
        em.node("triage", "working", "classifying…")
        em.node("openai", "working")
        em.edges("api-triage", "triage-openai")
        plan = deps.reasoner.plan(alert)
        em.say("Triage supervisor", f"Affected resource: {plan.resource}. Starting Logs, Metrics and Change agents in parallel.")
        em.node("triage", "done", "dispatched")
        em.node("openai", "done")
        return {"plan": plan.model_dump(), "rounds": 0}

    def gather(state, config, *, agent, who, start, edges, busy, fetch, working="querying…", done="1 finding", round=1):
        """An evidence agent: ask a connector, report what it found."""
        em, alert = _em(config), Alert(**state["alert"])
        em.node(agent, "working", working)
        for n in busy:
            em.node(n, "working")
        em.edges(*edges)
        em.say(who, start)
        evidence: Evidence = fetch(alert)
        em.say(who, evidence.summary)
        em.node(agent, "done", done)
        for n in busy:
            em.node(n, "done")
        return {"findings": {agent: Finding(agent=agent, summary=evidence.summary, round=round, detail=evidence.detail).model_dump()}}

    def logs(state: dict, config: RunnableConfig) -> dict:
        return gather(state, config, agent="logs", who="Logs agent", start="Running templated KQL on Log Analytics for the last 30 minutes.",
                      edges=["triage-logs", "logs-cl", "cl-azlog"], busy=["cl", "azlog"], fetch=lambda a: deps.logs.query(a))

    def metrics(state: dict, config: RunnableConfig) -> dict:
        return gather(state, config, agent="metrics", who="Metrics agent", start="Reading latency, error rate, CPU and memory from Azure Monitor.",
                      edges=["triage-metrics", "metrics-cm", "cm-azmet"], busy=["cm", "azmet"], fetch=lambda a: deps.metrics.query(a))

    def change(state: dict, config: RunnableConfig) -> dict:
        return gather(state, config, agent="change", who="Change agent", start="Listing deploys and config changes from the last 3 days.",
                      edges=["triage-change", "change-cc", "cc-azact", "cc-azpipe"], busy=["cc", "azact", "azpipe"], fetch=lambda a: deps.changes.recent(a))

    def logs_deeper(state: dict, config: RunnableConfig) -> dict:
        """A second pass by the Logs agent, when Diagnosis asks for more evidence."""
        return gather(state, config, agent="logs", who="Logs agent", start="Second pass: widening the window and pulling full stack traces.",
                      edges=["diagnosis-logs", "logs-cl", "cl-azlog"], busy=["cl", "azlog"], fetch=lambda a: deps.logs.query(a, deeper=True),
                      working="digging deeper…", done="2nd pass done", round=2)

    def diagnosis(state: dict, config: RunnableConfig) -> dict:
        em, alert = _em(config), Alert(**state["alert"])
        findings = {k: Finding(**v) for k, v in state["findings"].items()}
        rnd = state.get("rounds", 0) + 1
        em.edges("logs-diagnosis", "metrics-diagnosis", "change-diagnosis") if rnd == 1 else em.edges("logs-diagnosis")
        em.node("diagnosis", "working", "weighing…")
        d = deps.reasoner.diagnose(alert, findings, rnd)
        if d.needs_more and rnd < deps.max_rounds:
            em.node("diagnosis", "working", f"{_pct(d.confidence)} confident")
            em.say("Diagnosis agent", f"Confidence {_pct(d.confidence)}. {d.reason} Asking the Logs agent for a second pass.")
        else:
            if d.needs_more:
                em.say("Diagnosis agent", "Round limit reached. Continuing with the best explanation so far.")
            em.node("diagnosis", "done", f"{_pct(d.confidence)} confident")
            em.say("Diagnosis agent", f"Root cause: {d.cause} (confidence {_pct(d.confidence)}).")
        return {"diagnosis": d.model_dump(), "rounds": rnd}

    def remediation(state: dict, config: RunnableConfig) -> dict:
        em, alert, d = _em(config), Alert(**state["alert"]), Diagnosis(**state["diagnosis"])
        em.node("remediation", "working", "planning fix…")
        em.edges("diagnosis-remediation")
        p = deps.reasoner.propose_fix(alert, d)
        em.say("Remediation agent", f"Proposed fix: {p.action}. Risk: {p.risk}.")
        em.node("remediation", "done", "fix proposed")
        em.node("gate", "waiting", "needs you")
        em.edges("remediation-gate")
        em.say("Approval gate", "Paused. Nothing runs until the on-call engineer decides.")
        em.run("awaiting_approval")
        return {"proposal": p.model_dump()}

    def gate(state: dict, config: RunnableConfig) -> dict:
        # interrupt() must come first: when the run resumes, this node starts again from the top
        decision = interrupt({"proposal": state["proposal"]})
        em = _em(config)
        if decision == "approve":
            em.node("gate", "done", "approved")
            em.say("Approval gate", "Approved by the on-call engineer.")
        else:
            em.node("gate", "failed", "rejected")
            em.say("Approval gate", "Rejected by the on-call engineer. The fix will not be applied.")
        em.run("running")
        return {"approval": decision}

    def executor(state: dict, config: RunnableConfig) -> dict:
        em, alert, p = _em(config), Alert(**state["alert"]), FixProposal(**state["proposal"])
        em.node("executor", "working", "running fix…")
        em.node("carm", "working")
        em.node("azres", "working")
        em.edges("gate-executor", "executor-carm", "carm-azres")
        em.say("Action executor", f"Applying: {p.action}.")
        result = deps.actions.apply(alert, p)
        em.say("Action executor", result.message)
        em.node("executor", "done" if result.ok else "failed", "fixed" if result.ok else "failed")
        em.node("carm", "done")
        em.node("azres", "done")
        return {"action": result.model_dump()}

    def postmortem(state: dict, config: RunnableConfig) -> dict:
        em, alert = _em(config), Alert(**state["alert"])
        d, p = Diagnosis(**state["diagnosis"]), FixProposal(**state["proposal"])
        applied = state.get("approval") == "approve"
        fixed = applied and state.get("action", {}).get("ok", False)
        outcome = "fixed" if fixed else "unhealthy" if applied else "rejected"
        em.node("postmortem", "working", "writing…")
        em.edges("executor-postmortem", "gate-postmortem") if state.get("approval") == "approve" else em.edges("gate-postmortem")
        em.say("Postmortem agent", "Drafting timeline, cause and follow-ups." if fixed else "Drafting a report that records the diagnosis and the proposed fix.")
        pm = deps.reasoner.postmortem(alert, d, p, outcome)
        item = deps.work_items.create(alert, pm)
        em.node("cdo", "working")
        em.node("azbrd", "working")
        em.edges("postmortem-cdo", "cdo-azbrd")
        em.say("Postmortem agent", pm.summary)
        em.node("postmortem", "done", "filed")
        em.node("cdo", "done")
        em.node("azbrd", "done")
        em.say("Triage API", {
            "fixed": "Run closed: resolved with an approved fix.",
            "unhealthy": "Run closed: the fix was applied but the system is still unhealthy, handed to the on-call engineer.",
            "rejected": "Run closed: fix not applied, handed to the on-call engineer.",
        }[outcome])
        em.run("completed")
        return {"postmortem": pm.model_dump(), "work_item": item.model_dump()}

    return {
        "triage": triage, "logs": logs, "metrics": metrics, "change": change, "logs_deeper": logs_deeper,
        "diagnosis": diagnosis, "remediation": remediation, "gate": gate, "executor": executor, "postmortem": postmortem,
    }
