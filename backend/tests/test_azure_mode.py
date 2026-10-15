"""Azure mode as a whole: Azure Monitor's alert in, the agents on Azure-shaped evidence, and no action without a connector."""
import time

import pytest

pytest.importorskip("azure.monitor.query")

from fastapi.testclient import TestClient  # noqa: E402

from azurehelpers import CFG, FakeLogs, FakeMonitor, activity_event  # noqa: E402
from envhelpers import snapshot  # noqa: E402
from helpers import logs, wait_for  # noqa: E402
from triage.api import create_app  # noqa: E402
from triage.azure_alerts import from_common_alert_schema  # noqa: E402
from triage.connectors.azure import AzureActionsNotWired, AzureChanges, AzureLogs, AzureMetrics  # noqa: E402
from triage.connectors.demo import DemoWorkItems  # noqa: E402
from triage.deps import Deps, demo_deps  # noqa: E402
from triage.graph import build_graph  # noqa: E402
from triage.llm.rules import RuleReasoner  # noqa: E402
from triage.runs import RunManager  # noqa: E402

FIRED = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertId": "/subscriptions/sub-1/providers/Microsoft.AlertsManagement/alerts/b9569717-bc97-4f6b-9ddd-b42d0b8ba9d8",
            "alertRule": "shop-api failed requests above 5%",
            "severity": "Sev1",
            "signalType": "Log",
            "monitorCondition": "Fired",
            "monitoringService": "Log Alerts V2",
            "alertTargetIDs": ["/subscriptions/sub-1/resourcegroups/rg-shop/providers/microsoft.web/sites/shop-api"],
            "firedDateTime": "2026-10-15T14:02:11.123Z",
        }
    },
}


def azure_deps_from(name: str) -> Deps:
    snap = snapshot(name)
    now = snap["captured_at"]
    deploys = [activity_event("Microsoft.Resources/deployments/write", now - 2 * 86400, properties={"deploymentName": "shop-v481"}, display="Create Deployment"),
               activity_event("Microsoft.Resources/deployments/write", now - 180, properties={"deploymentName": "shop-v482"}, display="Create Deployment")]
    logs_client = FakeLogs(snap)
    return Deps(AzureLogs(logs_client, CFG, lambda: now), AzureMetrics(logs_client, CFG, lambda: now), AzureChanges(FakeMonitor(deploys), CFG, lambda: now),
                AzureActionsNotWired(), DemoWorkItems(), RuleReasoner())


# ---- the alert ----


def test_a_fired_alert_becomes_an_alert_with_the_resource_and_severity():
    a = from_common_alert_schema(FIRED)
    assert a.title == "shop-api failed requests above 5%" and a.resource == "shop-api" and a.severity == "high"
    assert a.id == "b9569717-bc97-4f6b-9ddd-b42d0b8ba9d8"
    assert a.labels["source"] == "azure-monitor" and a.labels["resource_id"].endswith("/sites/shop-api")


def test_a_resolved_alert_starts_nothing():
    resolved = {**FIRED, "data": {"essentials": {**FIRED["data"]["essentials"], "monitorCondition": "Resolved"}}}
    assert from_common_alert_schema(resolved) is None


@pytest.mark.parametrize("payload", [{}, {"schemaId": "other"}, {"schemaId": "azureMonitorCommonAlertSchema"}, {"schemaId": "azureMonitorCommonAlertSchema", "data": {"essentials": {}}}])
def test_anything_else_is_refused_with_a_reason(payload):
    with pytest.raises(ValueError):
        from_common_alert_schema(payload)


def client_for(name="bad-deploy"):
    return TestClient(create_app(demo_deps(), step_delay=0, env=azure_deps_from(name)))


def test_the_alerts_endpoint_starts_a_run_and_ignores_resolved(monkeypatch):
    monkeypatch.delenv("TRIAGE_ALERT_TOKEN", raising=False)
    c = client_for()
    r = c.post("/alerts", json=FIRED)
    assert r.status_code == 202 and r.json()["alert"]["resource"] == "shop-api"
    resolved = {**FIRED, "data": {"essentials": {**FIRED["data"]["essentials"], "monitorCondition": "Resolved"}}}
    assert c.post("/alerts", json=resolved).json() == {"ignored": "resolved"}
    assert len(c.get("/runs").json()) == 1


def test_the_alerts_endpoint_demands_the_token_when_one_is_configured(monkeypatch):
    monkeypatch.setenv("TRIAGE_ALERT_TOKEN", "s3cret")
    c = client_for()
    assert c.post("/alerts", json=FIRED).status_code == 401
    assert c.post("/alerts?token=wrong", json=FIRED).status_code == 401
    assert c.post("/alerts?token=s3cret", json=FIRED).status_code == 202
    assert c.post("/alerts?token=s3cret", json={"nope": 1}).status_code == 422


# ---- the agents on Azure-shaped evidence ----


def test_the_agents_diagnose_a_bad_deploy_from_azure_shaped_evidence_and_hand_over_the_fix():
    runs = RunManager(build_graph(demo_deps()), 0, build_graph(azure_deps_from("bad-deploy")))
    run = runs.start(from_common_alert_schema(FIRED))
    wait_for(run, "awaiting_approval")
    text = "\n".join(logs(run))
    assert "deploy v482 introduced AttributeError in PricingCalculator.apply_discount" in text
    assert "Proposed fix: roll shop-api back to v481" in text  # the previous deployment's version, read from the Activity Log
    runs.decide(run.id, "approve")
    wait_for(run, "completed")
    text = "\n".join(logs(run))
    assert "Azure actions are not wired yet" in text
    assert "Run closed: fix not applied, handed to the on-call engineer." in text  # approved, but nothing was done
    assert "the fix was applied" not in text
    assert [e.chip for e in run.events.after(0) if e.kind == "node" and e.node == "executor" and e.status == "failed"] == ["not applied"]


# ---- wiring ----


def test_azure_mode_builds_its_connectors_from_the_environment(monkeypatch):
    import azure.identity

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: object())  # no sign-in is attempted when building
    monkeypatch.setenv("TRIAGE_MODE", "azure")
    monkeypatch.setenv("AZURE_LOG_WORKSPACE_ID", "ws")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-shop")
    from triage.deps import configured_env_deps

    deps = configured_env_deps()
    assert isinstance(deps.logs, AzureLogs) and isinstance(deps.changes, AzureChanges) and isinstance(deps.actions, AzureActionsNotWired)


def test_an_unknown_mode_is_refused(monkeypatch):
    monkeypatch.setenv("TRIAGE_MODE", "gcp")
    from triage.deps import configured_env_deps

    with pytest.raises(ValueError, match="demo', 'env' or 'azure"):
        configured_env_deps()
