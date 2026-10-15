"""The whole graph, running on captured real telemetry with the rules-based reasoner."""
import pytest

from envhelpers import SCENARIOS, alert, env_deps_for
from helpers import logs, wait_for
from triage.api import create_app
from triage.deps import demo_deps
from triage.graph import build_graph
from triage.runs import RunManager


def run_env(name: str, decision: str):
    deps, calls = env_deps_for(name)
    runs = RunManager(build_graph(demo_deps()), 0, build_graph(deps))
    run = runs.start(alert(f"{name} alert"))
    wait_for(run, "awaiting_approval")
    runs.decide(run.id, decision)
    wait_for(run, "completed")
    return run, calls, deps


@pytest.mark.parametrize("name,endpoint,second_pass", [
    ("bad-deploy", "/actions/rollback", True),
    ("memory-leak", "/actions/restart", False),
    ("db-pool", "/actions/set-pool", True),
])
def test_approved_run_diagnoses_from_telemetry_and_applies_the_right_fix(name, endpoint, second_pass):
    run, calls, _ = run_env(name, "approve")
    text = "\n".join(logs(run))
    assert [c[0] for c in calls] == [endpoint]
    assert ("Asking the Logs agent for a second pass" in text) == second_pass
    assert "Root cause:" in text


def test_the_bad_deploy_is_diagnosed_and_rolled_back_to_the_previous_version():
    run, calls, _ = run_env("bad-deploy", "approve")
    text = "\n".join(logs(run))
    assert "deploy v482 introduced AttributeError in PricingCalculator.apply_discount" in text
    assert calls == [("/actions/rollback", {"to": "v481"})]


@pytest.mark.parametrize("name", SCENARIOS)
def test_a_rejected_run_touches_nothing(name):
    run, calls, deps = run_env(name, "reject")
    assert calls == []
    assert len(deps.work_items.created) == 1  # the postmortem still runs


def test_alerts_from_the_environment_use_it_and_demo_scenarios_stay_scripted():
    import time

    from fastapi.testclient import TestClient

    deps, _ = env_deps_for("bad-deploy")
    client = TestClient(create_app(demo_deps(), step_delay=0, env=deps))

    def finish(labels):
        rid = client.post("/runs", json={"title": "t", "resource": "r", "labels": labels}).json()["id"]
        for _ in range(500):
            if client.get(f"/runs/{rid}").json()["status"] == "awaiting_approval":
                break
            time.sleep(0.02)
        return "\n".join(f"{e['who']}: {e['text']}" for e in client.get(f"/runs/{rid}").json()["events"] if e["kind"] == "log")

    env_text = finish({"source": "demo-env"})
    assert "deploy v482 introduced" in env_text  # diagnosed from the captured telemetry
    scripted_text = finish({"demo_scenario": "memory-leak"})
    assert "memory leak in the running build, with no related change" in scripted_text  # the scripted scenario


def test_a_fix_that_does_not_heal_the_system_is_reported_as_unhealthy_not_as_unapplied():
    from triage.models import ActionResult

    deps, calls = env_deps_for("bad-deploy")
    deps.actions.apply = lambda alert, proposal: (calls.append(("applied", {})), ActionResult(ok=False, message="Rolled back. The shop is still unhealthy."))[1]
    runs = RunManager(build_graph(demo_deps()), 0, build_graph(deps))
    run = runs.start(alert("bad-deploy alert"))
    wait_for(run, "awaiting_approval")
    runs.decide(run.id, "approve")
    wait_for(run, "completed")
    text = "\n".join(logs(run))
    assert "the fix was applied but the system is still unhealthy" in text
    assert "but the system did not recover" in text
