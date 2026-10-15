"""The backend and the frontend share a vocabulary: node ids and link keys. If one side renames something, this fails."""
import re
from pathlib import Path

import pytest

from helpers import play
from triage.demo.scenarios import SCENARIOS

DIAGRAM = Path(__file__).resolve().parents[2] / "frontend/src/features/architecture/diagrams.ts"

pytestmark = pytest.mark.skipif(not DIAGRAM.exists(), reason="frontend sources not available")


def frontend_vocabulary():
    src = DIAGRAM.read_text(encoding="utf-8")
    nodes = set(re.findall(r'\w+: node\("(\w+)"', src))
    edges = {f"{a}-{b}" for a, b in re.findall(r'\{ from: "(\w+)", to: "(\w+)"', src)}
    return nodes, edges


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_every_node_and_link_the_backend_emits_exists_in_the_diagram(scenario, decision):
    nodes, edges = frontend_vocabulary()
    run, _ = play(scenario, decision)
    events = run.events.after(0)
    emitted_nodes = {e.node for e in events if e.kind == "node"}
    emitted_edges = {k for e in events if e.kind == "edges" for k in e.edges}
    assert emitted_nodes <= nodes, emitted_nodes - nodes
    assert emitted_edges <= edges, emitted_edges - edges


def test_an_approved_run_lights_up_every_agent():
    nodes, _ = frontend_vocabulary()
    run, _ = play("bad-deploy", "approve")
    done = {e.node for e in run.events.after(0) if e.kind == "node" and e.status == "done"}
    for agent in ("triage", "logs", "metrics", "change", "diagnosis", "remediation", "executor", "postmortem"):
        assert agent in done and agent in nodes
