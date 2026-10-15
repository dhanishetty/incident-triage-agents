import pytest

pytest.importorskip("azure.monitor.query")

from azure.monitor.query import LogsQueryPartialResult, LogsTable  # noqa: E402

from azurehelpers import CFG, FakeLogs, FakeMonitor, activity_event, close, iso, table  # noqa: E402
from envhelpers import SCENARIOS, alert, shop_client, snapshot  # noqa: E402
from triage.connectors.azure import AzureChanges, AzureConfig, AzureLogs, AzureMetrics, epoch, logs_kql, parse_frames, requests_kql  # noqa: E402
from triage.connectors.env import EnvLogs, EnvMetrics  # noqa: E402


# ---- parity: Azure and the demo environment must produce the same evidence from the same telemetry ----


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("deeper", [False, True])
def test_azure_logs_give_the_same_evidence_as_the_demo_environment(name, deeper):
    snap = snapshot(name)
    azure = AzureLogs(FakeLogs(snap), CFG, clock=lambda: snap["captured_at"]).query(alert(), deeper=deeper)
    shop, _ = shop_client(name)
    env = EnvLogs(shop).query(alert(), deeper=deeper)
    assert azure.summary == env.summary
    close(azure.detail, env.detail)


@pytest.mark.parametrize("name", SCENARIOS)
def test_azure_metrics_give_the_same_evidence_as_the_demo_environment(name):
    snap = snapshot(name)
    azure = AzureMetrics(FakeLogs(snap), CFG).query(alert())
    shop, _ = shop_client(name)
    env = EnvMetrics(shop).query(alert())
    assert azure.summary == env.summary
    close(azure.detail, env.detail)


# ---- what is sent to Azure ----


def test_queries_go_to_the_configured_workspace_and_window_and_filter_on_the_app_role():
    fake = FakeLogs(snapshot("bad-deploy"))
    AzureLogs(fake, CFG).query(alert())
    workspace, kql, timespan = fake.queries[0]
    assert workspace == "ws-1234" and timespan.total_seconds() == 30 * 60
    assert 'AppRoleName == "shop-api"' in kql and "SeverityLevel >= 3" in kql and "ago(30m)" in kql


def test_metrics_make_two_queries_requests_and_gauges():
    fake = FakeLogs(snapshot("memory-leak"))
    AzureMetrics(fake, CFG).query(alert())
    assert [q[1].split("\n")[0] for q in fake.queries] == ["AppRequests", "AppMetrics"]
    assert '"shop.mem_mb"' in fake.queries[1][1]


@pytest.mark.parametrize("bad", ['x" or 1 == 1 //', "a\nb", "role; drop", "", "x" * 101])
def test_values_that_could_alter_a_query_are_refused(bad):
    with pytest.raises(ValueError):
        AzureConfig("ws", "sub", "rg", app_role=bad)
    with pytest.raises(ValueError):
        AzureConfig("ws", "sub", bad or "rg;", app_role="ok")
    with pytest.raises(ValueError):
        AzureConfig("ws", "sub", "rg", gauges={"mem_mb": bad or "a b"})


def test_config_comes_from_the_environment_and_names_what_is_missing(monkeypatch):
    for name in ("AZURE_LOG_WORKSPACE_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_APP_ROLE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(KeyError, match="AZURE_LOG_WORKSPACE_ID, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP"):
        AzureConfig.from_env()
    monkeypatch.setenv("AZURE_LOG_WORKSPACE_ID", "w")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "s")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-x")
    monkeypatch.setenv("AZURE_APP_ROLE", "checkout")
    cfg = AzureConfig.from_env()
    assert (cfg.workspace_id, cfg.resource_group, cfg.app_role) == ("w", "rg-x", "checkout")


# ---- handling Azure's answers ----


def test_a_partial_result_is_used_as_far_as_it_goes():
    class Partial:
        def query_workspace(self, *a, **kw):
            t = LogsTable(name="PrimaryResult", columns=["ts", "msg", "frames"], columns_types=["datetime", "string", "string"], rows=[[iso(1000.0), "boom", ""]])
            return LogsQueryPartialResult(partial_data=[t])

    ev = AzureLogs(Partial(), CFG, clock=lambda: 1060.0).query(alert())
    assert ev.detail["total"] == 1 and "boom" in ev.summary


def test_an_empty_result_means_no_errors():
    class Empty:
        def query_workspace(self, *a, **kw):
            return table(["ts", "msg", "frames"], ["datetime", "string", "string"], [])

    assert "No errors" in AzureLogs(Empty(), CFG).query(alert()).summary


def test_a_failed_query_is_not_swallowed():
    class Boom:
        def query_workspace(self, *a, **kw):
            raise RuntimeError("workspace not found")

    with pytest.raises(RuntimeError, match="workspace not found"):
        AzureLogs(Boom(), CFG).query(alert())


def test_frames_arrive_as_json_text_a_list_or_nothing():
    assert parse_frames('["a.py:f", "b.py:g"]') == ["a.py:f", "b.py:g"]
    assert parse_frames(["x"]) == ["x"] and parse_frames("") == [] and parse_frames(None) == []
    assert parse_frames("not json") == ["not json"]


def test_timestamps_may_be_datetimes_numbers_or_iso_text():
    assert epoch(1000.5) == 1000.5
    assert epoch("1970-01-01T00:16:40Z") == 1000.0
    from datetime import datetime

    assert epoch(datetime(1970, 1, 1, 0, 16, 40)) == 1000.0  # a naive datetime is taken as UTC


def test_kql_templates_are_stable_text():
    assert logs_kql("shop-api", 30).splitlines()[0] == "AppTraces"
    assert "percentile(DurationMs, 95)" in requests_kql("shop-api", 30)


# ---- the Activity Log ----

NOW = 1_800_000_000.0


def changes(events):
    monitor = FakeMonitor(events)
    return AzureChanges(monitor, CFG, clock=lambda: NOW).recent(alert()), monitor


def test_deploys_and_config_writes_are_read_from_the_resource_groups_activity_log():
    ev, monitor = changes([
        activity_event("Microsoft.Resources/deployments/write", NOW - 2 * 86400, properties={"deploymentName": "shop-v481"}, display="Create Deployment"),
        activity_event("Microsoft.Resources/deployments/write", NOW - 180, properties={"deploymentName": "shop-v482"}, display="Create Deployment"),
        activity_event("Microsoft.Web/sites/config/write", NOW - 3600, display="Update web app configuration"),
    ])
    assert "resourceGroupName eq 'rg-shop'" in monitor.filters[0] and "eventTimestamp ge '" in monitor.filters[0]
    rows = ev.detail["changes"]
    assert [r["kind"] for r in rows] == ["deploy", "config", "deploy"]  # newest first
    newest = rows[0]
    assert newest["meta"]["version"] == "v482" and newest["meta"]["from_version"] == "v481"
    assert newest["age_min"] == pytest.approx(3)
    assert "Create Deployment on shop-api by ci@example.com" in newest["detail"]


def test_events_that_are_not_successful_administrative_writes_are_ignored():
    ev, _ = changes([
        activity_event("Microsoft.Resources/deployments/write", NOW - 60, status="Started"),
        activity_event("Microsoft.Resources/deployments/write", NOW - 60, status="Failed"),
        activity_event("Microsoft.Web/sites/read", NOW - 60),
        activity_event("Microsoft.Web/sites/config/write", NOW - 60, category="Autoscale"),
    ])
    assert ev.detail["changes"] == [] and "No deploys or config changes in the last 3 days" in ev.summary


def test_a_deploy_without_a_version_in_its_name_still_shows_up():
    ev, _ = changes([activity_event("Microsoft.Resources/deployments/write", NOW - 60, properties={"deploymentName": "release-2026-10"})])
    row = ev.detail["changes"][0]
    assert row["kind"] == "deploy" and "version" not in row["meta"]
