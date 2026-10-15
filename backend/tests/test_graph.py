import pytest

from helpers import alert, logs, manager, play, wait_for
from triage.demo.scenarios import SCENARIOS
from triage.runs import NotAwaitingApproval


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_approved_run_applies_the_fix_and_files_the_report(scenario):
    run, deps = play(scenario, "approve")
    s = SCENARIOS[scenario]
    assert deps.actions.applied == [s.fix]
    assert len(deps.work_items.created) == 1
    assert any(s.cause in line for line in logs(run))


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_rejected_run_changes_nothing_but_still_files_the_report(scenario):
    run, deps = play(scenario, "reject")
    assert deps.actions.applied == []  # the guardrail: nothing runs without approval
    assert len(deps.work_items.created) == 1  # the postmortem always runs
    assert any("Rejected" in line for line in logs(run))


def test_diagnosis_asks_for_more_evidence_when_unsure():
    run, _ = play("bad-deploy", "approve")
    text = "\n".join(logs(run))
    assert "Asking the Logs agent for a second pass" in text
    assert SCENARIOS["bad-deploy"].logs_deeper in text
    assert "91%" in text


def test_diagnosis_does_not_loop_when_confident():
    run, _ = play("memory-leak", "approve")
    text = "\n".join(logs(run))
    assert "second pass" not in text.lower()


def test_run_waits_at_the_gate_until_a_person_decides():
    runs, deps = manager()
    run = runs.start(alert("bad-deploy"))
    wait_for(run, "awaiting_approval")
    assert deps.actions.applied == []
    assert [e.status for e in run.events.after(0) if e.kind == "node" and e.node == "gate"] == ["waiting"]


def test_a_decision_is_only_accepted_while_waiting():
    runs, _ = manager()
    run = runs.start(alert("memory-leak"))
    wait_for(run, "awaiting_approval")
    runs.decide(run.id, "approve")
    with pytest.raises(NotAwaitingApproval):
        runs.decide(run.id, "approve")


def test_evidence_agents_run_in_parallel():
    """Each evidence connector waits for the other two. The run only gets through if all three agents run at once."""
    import threading

    from triage.deps import demo_deps
    from triage.graph import build_graph
    from triage.runs import RunManager

    barrier = threading.Barrier(3, timeout=5)
    deps = demo_deps()
    logs, metrics, changes = deps.logs, deps.metrics, deps.changes

    class Logs:
        def query(self, a, *, deeper=False):
            if not deeper:
                barrier.wait()
            return logs.query(a, deeper=deeper)

    class Metrics:
        def query(self, a):
            barrier.wait()
            return metrics.query(a)

    class Changes:
        def recent(self, a):
            barrier.wait()
            return changes.recent(a)

    deps.logs, deps.metrics, deps.changes = Logs(), Metrics(), Changes()
    run = RunManager(build_graph(deps)).start(alert("memory-leak"))
    wait_for(run, "awaiting_approval")  # a sequential graph would break the barrier and fail the run


def test_the_diagnosis_round_limit_stops_endless_loops():
    from triage.deps import demo_deps
    from triage.graph import build_graph
    from triage.models import Diagnosis
    from triage.runs import RunManager

    class NeverSure:
        def __getattr__(self, name):  # reuse the scripted reasoner for everything but diagnose
            from triage.llm.fake import ScriptedReasoner
            return getattr(ScriptedReasoner(), name)

        def diagnose(self, alert, findings, round):
            return Diagnosis(cause="unclear", confidence=0.3, needs_more=True, reason="Still unsure.")

    deps = demo_deps()
    deps.reasoner = NeverSure()
    runs = RunManager(build_graph(deps))
    run = runs.start(alert("bad-deploy"))
    wait_for(run, "awaiting_approval")
    assert "Round limit reached" in "\n".join(logs(run))
