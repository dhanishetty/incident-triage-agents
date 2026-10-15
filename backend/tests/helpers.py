import time

from triage.deps import Deps, demo_deps
from triage.graph import build_graph
from triage.models import Alert
from triage.runs import Run, RunManager


def alert(scenario: str) -> Alert:
    return Alert(title=f"demo {scenario}", resource="demo", labels={"demo_scenario": scenario})


def wait_for(run: Run, status: str, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if run.status == status:
            return
        if run.status == "failed":
            raise AssertionError(f"run failed: {run.error}")
        time.sleep(0.02)
    raise AssertionError(f"run is {run.status!r}, expected {status!r}")


def manager() -> tuple[RunManager, Deps]:
    deps = demo_deps()
    return RunManager(build_graph(deps), step_delay=0), deps


def play(scenario: str, decision: str) -> tuple[Run, Deps]:
    """Run one incident to the end, deciding at the gate."""
    runs, deps = manager()
    run = runs.start(alert(scenario))
    wait_for(run, "awaiting_approval")
    runs.decide(run.id, decision)
    wait_for(run, "completed")
    return run, deps


def logs(run: Run) -> list[str]:
    return [f"{e.who}: {e.text}" for e in run.events.after(0) if e.kind == "log"]
