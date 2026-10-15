"""Fake Azure clients that answer from a captured snapshot, using the SDK's real result classes.

The snapshot (tests/fixtures/*.json) is real telemetry captured from the demo shop. These helpers dress it the way
Log Analytics and the Activity Log would return it, so the Azure connectors can be tested without Azure.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from azure.monitor.query import LogsQueryResult, LogsTable

from envhelpers import snapshot
from triage.connectors.azure import GAUGES, AzureConfig

CFG = AzureConfig(workspace_id="ws-1234", subscription_id="sub-1", resource_group="rg-shop", app_role="shop-api")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def table(columns: list[str], types: list[str], rows: list[list]) -> LogsQueryResult:
    return LogsQueryResult(tables=[LogsTable(name="PrimaryResult", columns=columns, columns_types=types, rows=rows)])


class FakeLogs:
    """Answers the three KQL templates from a snapshot, and remembers what it was asked."""

    def __init__(self, snap: dict) -> None:
        self.snap = snap
        self.queries: list[tuple[str, str, object]] = []

    def query_workspace(self, workspace_id, query, *, timespan, **kw):
        self.queries.append((workspace_id, query, timespan))
        s = self.snap
        if query.startswith("AppTraces"):
            return table(["ts", "msg", "frames"], ["datetime", "string", "string"], [[iso(e["ts"]), e["msg"], json.dumps(e.get("frames", []))] for e in s["logs"]])
        if query.startswith("AppRequests"):
            return table(["ts", "rps", "error_rate", "p95_ms"], ["datetime", "long", "real", "real"], [[iso(m["ts"]), m["rps"], m["error_rate"], m["p95_ms"]] for m in s["metrics"]])
        if query.startswith("AppMetrics"):
            rows = [[name, iso(m["ts"]), float(m[field])] for m in s["metrics"] for field, name in GAUGES.items()]
            return table(["Name", "ts", "v"], ["string", "datetime", "real"], rows)
        raise AssertionError(f"unexpected query: {query[:40]}")


def activity_event(operation: str, ts: float, resource: str = "shop-api", *, status="Succeeded", category="Administrative", caller="ci@example.com", properties=None, display=None):
    return SimpleNamespace(
        operation_name=SimpleNamespace(value=operation, localized_value=display or operation),
        status=SimpleNamespace(value=status),
        category=SimpleNamespace(value=category),
        resource_id=f"/subscriptions/sub-1/resourceGroups/rg-shop/providers/Microsoft.Web/sites/{resource}",
        caller=caller,
        event_timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        properties=properties or {},
    )


class FakeMonitor:
    def __init__(self, events: list) -> None:
        self.filters: list[str] = []
        self.activity_logs = SimpleNamespace(list=lambda filter: (self.filters.append(filter), iter(events))[1])


def close(a, b, rel=1e-6):
    """Equal, allowing for float noise from a timestamp's round trip through text."""
    if isinstance(a, dict):
        assert a.keys() == b.keys(), (a.keys(), b.keys())
        for k in a:
            close(a[k], b[k], rel)
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            close(x, y, rel)
    elif isinstance(a, float) or isinstance(b, float):
        assert abs(a - b) <= rel * max(1, abs(a), abs(b)), (a, b)
    else:
        assert a == b, (a, b)
