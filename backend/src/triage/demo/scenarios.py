"""The three demo incidents. Same facts as the frontend replay (frontend/src/features/architecture/scenarios.ts).

An alert picks one with the label `demo_scenario`. The demo connectors serve these facts as if they came from Azure,
and the scripted reasoner draws its conclusions from them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoScenario:
    id: str
    alert: str
    resource: str
    logs: str
    metrics: str
    change: str
    confidence: float
    cause: str
    fix: str
    risk: str
    fix_result: str
    report: str
    logs_deeper: str | None = None
    first_confidence: float | None = None  # set when the first pass is not convincing and Diagnosis asks for more
    why_unsure: str = ""


SCENARIOS: dict[str, DemoScenario] = {
    s.id: s
    for s in [
        DemoScenario(
            id="bad-deploy",
            alert="orders-api p95 latency above 2 s for 5 minutes",
            resource="orders-api (App Service, production)",
            logs="NullReferenceException in PricingCalculator, first seen 14:02, 340 times in 10 minutes.",
            logs_deeper="Full stack traces all end in PricingCalculator.ApplyDiscount, added in the latest release.",
            metrics="HTTP 5xx rate rose from 0.2% to 9% at 14:02. CPU and memory are normal.",
            change="Deploy #482 finished at 14:01 and changed the pricing module.",
            first_confidence=0.62,
            why_unsure="The errors start right after a deploy, but the log lines do not yet name the changed code.",
            confidence=0.91,
            cause="deploy #482 introduced a null reference in the pricing module",
            fix="roll orders-api back to deploy #481",
            risk="low, #481 ran cleanly for 6 days",
            fix_result="Rollback to #481 complete. 5xx rate back to 0.2% within 2 minutes.",
            report="Work item created: bad deploy #482, rollback to #481, follow-up to add a pricing test.",
        ),
        DemoScenario(
            id="memory-leak",
            alert="checkout-api restarted 6 times in one hour",
            resource="checkout-api (AKS, 3 pods)",
            logs="OOMKilled events on all three pods, roughly every 9 minutes.",
            metrics="Memory climbs in a straight line from 300 MB to the 1 GB limit between restarts.",
            change="No deploys or config changes in the last 48 hours.",
            confidence=0.88,
            cause="a memory leak in the running build, with no related change",
            fix="restart the pods now and raise the memory limit to 2 GB as a stopgap",
            risk="medium, a rolling restart briefly lowers capacity",
            fix_result="Rolling restart complete and the new limit applied. Memory is stable at 380 MB.",
            report="Work item created: suspected leak in checkout-api, stopgap applied, follow-up to profile the heap.",
        ),
        DemoScenario(
            id="db-connections",
            alert="payments-api failing requests with timeouts",
            resource="payments-api and its Azure SQL database",
            logs="Timeouts waiting for a connection from the pool, 1,200 in 15 minutes.",
            logs_deeper="Pool errors begin the moment morning traffic doubles, not at a fixed time.",
            metrics="Database connections sit at 100 of 100. CPU on the database is only 30%.",
            change="Config change 2 days ago lowered the connection pool size from 200 to 50.",
            first_confidence=0.70,
            why_unsure="The pool change fits, but the timing of the failures is not yet explained.",
            confidence=0.93,
            cause="the pool size was cut to 50 and now runs out under peak traffic",
            fix="set the connection pool size back to 200 and restart the app",
            risk="low, it restores the previous setting",
            fix_result="Pool size restored. Connections peak at 140 of 200 and timeouts stop.",
            report="Work item created: pool size regression, config restored, follow-up to load-test pool settings.",
        ),
    ]
}

DEFAULT = "bad-deploy"


def scenario_for(labels: dict[str, str]) -> DemoScenario:
    return SCENARIOS.get(labels.get("demo_scenario", DEFAULT), SCENARIOS[DEFAULT])
