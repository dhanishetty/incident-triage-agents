"""Azure Monitor's common alert schema, turned into the Alert the agents work from.

An Action Group webhook posts this JSON when an alert rule fires (and again when it resolves).
https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-common-schema
"""
from __future__ import annotations

from triage.models import Alert

SCHEMA = "azureMonitorCommonAlertSchema"
SEVERITY = {"Sev0": "critical", "Sev1": "high", "Sev2": "medium", "Sev3": "low", "Sev4": "low"}


def _last(resource_id: str) -> str:
    return resource_id.rstrip("/").rsplit("/", 1)[-1]


def from_common_alert_schema(payload: dict) -> Alert | None:
    """The Alert for a fired alert, or None when it is a resolve notification. Raises ValueError for any other JSON."""
    if payload.get("schemaId") != SCHEMA:
        raise ValueError(f"Expected schemaId {SCHEMA!r}. Enable the common alert schema on the Action Group's webhook.")
    try:
        e = payload["data"]["essentials"]
        if e.get("monitorCondition") == "Resolved":
            return None
        targets = e.get("alertTargetIDs") or []
        return Alert(
            id=_last(e["alertId"]),
            title=e["alertRule"],
            resource=_last(targets[0]) if targets else "unknown resource",
            severity=SEVERITY.get(e.get("severity", ""), "medium"),
            labels={
                "source": "azure-monitor",
                "rule": e["alertRule"],
                "signal_type": str(e.get("signalType", "")),
                "monitoring_service": str(e.get("monitoringService", "")),
                "fired_at": str(e.get("firedDateTime", "")),
                **({"resource_id": targets[0]} if targets else {}),
            },
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"The alert payload is missing {exc}") from exc
