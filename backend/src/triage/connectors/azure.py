"""Azure connectors: read Application Insights telemetry in Log Analytics, and the subscription's Activity Log.

They only fetch and normalise. Each one turns Azure's answer into the row shapes described in analysis.py, and the
shared analysis builds the evidence, so the reasoner sees the same kind of evidence from Azure as from the demo
environment.

  AzureLogs     error-level traces (AppTraces) in a workspace, by KQL
  AzureMetrics  request failure rate and p95 (AppRequests), plus gauges the app reports (AppMetrics), by KQL
  AzureChanges  deploys and config writes from the Activity Log of one resource group

All three are read-only. They need `Log Analytics Reader` on the workspace and `Reader` (or `Monitoring Reader`) on
the resource group. Azure's Action connector is not built yet, so approved fixes are handed to a person.

KQL is built from templates. The only values that go into it come from configuration, never from an alert, and they
are checked against a strict pattern, because the Logs SDK has no query parameters to bind.
"""
from __future__ import annotations

import json
import os
import re
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from triage.connectors.analysis import changes_evidence, logs_evidence, metrics_evidence
from triage.models import ActionResult, Alert, Evidence, FixProposal

Clock = Callable[[], float]

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.\- ]{1,100}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.]{1,100}$")
_SAFE_GROUP = re.compile(r"^[A-Za-z0-9_.()\-]{1,90}$")

GAUGES = {"mem_mb": "shop.mem_mb", "restarts": "shop.restarts", "db_in_use": "shop.db_in_use", "db_pool": "shop.db_pool"}


@dataclass(frozen=True)
class AzureConfig:
    workspace_id: str  # the Log Analytics workspace (customer) id
    subscription_id: str
    resource_group: str
    app_role: str = "shop-api"  # the cloud role name the app reports its telemetry under
    gauges: dict[str, str] = field(default_factory=lambda: dict(GAUGES))  # field name -> custom metric name
    log_window_min: int = 30
    metrics_window_min: int = 30
    change_hours: int = 72
    version_pattern: str = r"\bv\d+(?:\.\d+)*\b"  # how a version looks in a deployment's name or description

    def __post_init__(self) -> None:
        if not _SAFE_VALUE.fullmatch(self.app_role):
            raise ValueError(f"app_role {self.app_role!r} has characters that are not allowed in a KQL filter")
        if not _SAFE_GROUP.fullmatch(self.resource_group):
            raise ValueError(f"resource_group {self.resource_group!r} has characters that are not allowed in an Activity Log filter")
        for name in self.gauges.values():
            if not _SAFE_NAME.fullmatch(name):
                raise ValueError(f"metric name {name!r} has characters that are not allowed in a KQL filter")

    @classmethod
    def from_env(cls) -> "AzureConfig":
        need = ["AZURE_LOG_WORKSPACE_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP"]
        missing = [n for n in need if not os.getenv(n)]
        if missing:
            raise KeyError(f"TRIAGE_MODE=azure needs these environment variables: {', '.join(missing)}")
        return cls(os.environ[need[0]], os.environ[need[1]], os.environ[need[2]], os.getenv("AZURE_APP_ROLE", "shop-api"))


# ---- KQL templates ------------------------------------------------------------------------------------------------


def logs_kql(role: str, minutes: int, limit: int = 2000) -> str:
    return (
        f"AppTraces\n"
        f"| where TimeGenerated > ago({int(minutes)}m)\n"
        f'| where AppRoleName == "{role}" and SeverityLevel >= 3\n'  # 3 = error, 4 = critical
        f"| project ts = TimeGenerated, msg = Message, frames = tostring(Properties.frames)\n"
        f"| order by ts asc\n"
        f"| take {int(limit)}"
    )


def requests_kql(role: str, minutes: int) -> str:
    return (
        f"AppRequests\n"
        f"| where TimeGenerated > ago({int(minutes)}m)\n"
        f'| where AppRoleName == "{role}"\n'
        f"| summarize rps = count(), failed = countif(Success == false), p95_ms = percentile(DurationMs, 95) by ts = bin(TimeGenerated, 1s)\n"
        f"| project ts, rps, error_rate = todouble(failed) / rps, p95_ms\n"
        f"| order by ts asc"
    )


def gauges_kql(role: str, minutes: int, names: list[str]) -> str:
    listed = ", ".join(f'"{n}"' for n in names)
    return (
        f"AppMetrics\n"
        f"| where TimeGenerated > ago({int(minutes)}m)\n"
        f'| where AppRoleName == "{role}" and Name in ({listed})\n'
        f"| summarize v = avg(Sum / ValueCount) by Name, ts = bin(TimeGenerated, 1s)\n"
        f"| order by ts asc"
    )


# ---- helpers ------------------------------------------------------------------------------------------------------


def run_kql(client: Any, workspace_id: str, kql: str, minutes: int) -> list[dict]:
    """Run a query and return the first table as dicts. A partial result is used as far as it goes."""
    result = client.query_workspace(workspace_id, kql, timespan=timedelta(minutes=minutes))
    status = str(getattr(result.status, "value", result.status))
    tables = result.partial_data if status == "PartialError" else result.tables
    if not tables:
        return []
    table = tables[0]
    columns = [c if isinstance(c, str) else c.name for c in table.columns]
    return [dict(zip(columns, row)) for row in table.rows]


def epoch(value: Any) -> float:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def parse_frames(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        parsed = json.loads(value)
        return [str(v) for v in parsed] if isinstance(parsed, list) else [str(parsed)]
    except (TypeError, ValueError):
        return [str(value)]


# ---- connectors ---------------------------------------------------------------------------------------------------


class AzureLogs:
    def __init__(self, logs_client: Any, cfg: AzureConfig, clock: Clock = time.time) -> None:
        self.client, self.cfg, self.clock = logs_client, cfg, clock

    def query(self, alert: Alert, *, deeper: bool = False) -> Evidence:
        rows = run_kql(self.client, self.cfg.workspace_id, logs_kql(self.cfg.app_role, self.cfg.log_window_min), self.cfg.log_window_min)
        errors = [{"ts": epoch(r["ts"]), "msg": r["msg"], "frames": parse_frames(r.get("frames"))} for r in rows]
        return logs_evidence(errors, self.clock(), deeper, self.cfg.log_window_min)


class AzureMetrics:
    def __init__(self, logs_client: Any, cfg: AzureConfig, clock: Clock = time.time) -> None:
        self.client, self.cfg, self.clock = logs_client, cfg, clock

    def query(self, alert: Alert) -> Evidence:
        cfg = self.cfg
        requests = run_kql(self.client, cfg.workspace_id, requests_kql(cfg.app_role, cfg.metrics_window_min), cfg.metrics_window_min)
        gauges = run_kql(self.client, cfg.workspace_id, gauges_kql(cfg.app_role, cfg.metrics_window_min, list(cfg.gauges.values())), cfg.metrics_window_min)

        # Gauges are reported less often than every second, so carry each reading forward to the seconds after it.
        series: dict[str, tuple[list[float], list[float]]] = {}
        for g in sorted(gauges, key=lambda r: epoch(r["ts"])):
            times, values = series.setdefault(g["Name"], ([], []))
            times.append(epoch(g["ts"]))
            values.append(float(g["v"]))

        def gauge(field_name: str, ts: float) -> float:
            times, values = series.get(cfg.gauges[field_name], ([], []))
            if not times:
                return 0.0
            return values[max(0, bisect_right(times, ts) - 1)]

        samples = [
            {
                "ts": epoch(r["ts"]),
                "rps": r["rps"],
                "error_rate": float(r["error_rate"]),
                "p95_ms": float(r["p95_ms"]),
                **{f: gauge(f, epoch(r["ts"])) for f in cfg.gauges},
            }
            for r in requests
        ]
        return metrics_evidence(samples)


DEPLOY_OPERATIONS = ("deployments/write", "sites/publish", "slotsswap", "revisions")


def _name(x: Any) -> str:
    """Azure wraps many values as {value, localized_value}; take the plain one."""
    return str(getattr(x, "value", x) or "")


class AzureChanges:
    """Deploys and config writes from the Activity Log of one resource group."""

    def __init__(self, monitor_client: Any, cfg: AzureConfig, clock: Clock = time.time) -> None:
        self.client, self.cfg, self.clock = monitor_client, cfg, clock

    def recent(self, alert: Alert) -> Evidence:
        cfg, now = self.cfg, self.clock()
        since = datetime.fromtimestamp(now - cfg.change_hours * 3600, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        events = self.client.activity_logs.list(filter=f"eventTimestamp ge '{since}' and resourceGroupName eq '{cfg.resource_group}'")

        rows = []
        for e in events:
            op = _name(e.operation_name)
            if _name(e.status) != "Succeeded" or _name(e.category) != "Administrative" or not op.lower().endswith(("/write", "/action")):
                continue
            resource_id = e.resource_id or ""
            display = getattr(e.operation_name, "localized_value", None) or op
            detail = f"{display} on {resource_id.rsplit('/', 1)[-1] or cfg.resource_group} by {e.caller or 'unknown'}"
            haystack = f"{detail} {resource_id} {json.dumps(e.properties or {}, default=str)}"
            version = re.search(cfg.version_pattern, haystack)
            rows.append(
                {
                    "ts": epoch(e.event_timestamp),
                    "kind": "deploy" if any(d in op.lower() for d in DEPLOY_OPERATIONS) else "config",
                    "detail": detail,
                    "meta": {"operation": op, "resource": resource_id, **({"version": version.group(0)} if version else {})},
                }
            )

        # A deploy's "from" version is the one before it, so a rollback target can be named.
        previous = None
        for row in sorted((r for r in rows if r["kind"] == "deploy"), key=lambda r: r["ts"]):
            version = row["meta"].get("version")
            if version and previous and previous != version:
                row["meta"]["from_version"] = previous
            previous = version or previous
        return changes_evidence(rows, now, f"{cfg.change_hours // 24} days")


class AzureActionsNotWired:
    """Azure has no Action connector yet, so an approved fix is handed to a person instead of applied."""

    def apply(self, alert: Alert, proposal: FixProposal) -> ActionResult:
        return ActionResult(ok=False, applied=False, message="Azure actions are not wired yet. Handing over to the on-call engineer.")
