"""The agent graph: the same flow the frontend draws.

    triage -> logs / metrics / change (parallel) -> diagnosis -> remediation -> gate (pauses for a person)
    diagnosis may loop back to a second Logs pass (capped), the gate decides between executor and postmortem,
    and the postmortem always runs.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from triage.agents import make_nodes
from triage.deps import Deps


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class State(TypedDict, total=False):
    alert: dict
    plan: dict
    findings: Annotated[dict, _merge]  # the evidence agents write to separate keys in parallel
    rounds: int
    diagnosis: dict
    proposal: dict
    approval: str
    action: dict
    postmortem: dict
    work_item: dict


def build_graph(deps: Deps):
    nodes = make_nodes(deps)
    g = StateGraph(State)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "triage")
    for evidence in ("logs", "metrics", "change"):
        g.add_edge("triage", evidence)  # fan out: all three start together
    g.add_edge(["logs", "metrics", "change"], "diagnosis")  # fan in: Diagnosis waits for all three
    g.add_edge("logs_deeper", "diagnosis")

    def after_diagnosis(state: State) -> str:
        return "more" if state["diagnosis"]["needs_more"] and state["rounds"] < deps.max_rounds else "fix"

    g.add_conditional_edges("diagnosis", after_diagnosis, {"more": "logs_deeper", "fix": "remediation"})
    g.add_edge("remediation", "gate")
    g.add_conditional_edges("gate", lambda s: "act" if s["approval"] == "approve" else "skip", {"act": "executor", "skip": "postmortem"})
    g.add_edge("executor", "postmortem")
    g.add_edge("postmortem", END)
    return g.compile(checkpointer=InMemorySaver())
