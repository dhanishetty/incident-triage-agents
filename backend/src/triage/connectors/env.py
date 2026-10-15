"""Connectors for the demo environment (demo_env/shop): they read its telemetry API and hand the rows to the shared analysis.

The Azure connectors (azure.py) do the same against Log Analytics and the Activity Log.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable

import httpx

from triage.connectors.analysis import age, changes_evidence, logs_evidence, metrics_evidence, signature  # noqa: F401  (age, signature re-exported)
from triage.models import ActionResult, Alert, Evidence, FixProposal

Clock = Callable[[], float]


class ShopClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None, clock: Clock = time.time) -> None:
        self.http = http or httpx.Client(base_url=base_url, timeout=10)
        self.clock = clock

    def get(self, path: str, **params):
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, **params):
        r = self.http.post(path, params=params)
        r.raise_for_status()
        return r.json()


class EnvLogs:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def query(self, alert: Alert, *, deeper: bool = False) -> Evidence:
        errors = self.shop.get("/telemetry/logs", minutes=30, level="ERROR")
        return logs_evidence(errors, self.shop.clock(), deeper)


class EnvMetrics:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def query(self, alert: Alert) -> Evidence:
        return metrics_evidence(self.shop.get("/telemetry/metrics", minutes=30))


class EnvChanges:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def recent(self, alert: Alert) -> Evidence:
        return changes_evidence(self.shop.get("/telemetry/changes", hours=72), self.shop.clock())


class EnvActions:
    """Applies an approved fix to the shop, waits a moment, then checks that the shop really recovered."""

    def __init__(self, shop: ShopClient, verify_wait: float = 6.0) -> None:
        self.shop = shop
        self.verify_wait = verify_wait

    def apply(self, alert: Alert, proposal: FixProposal) -> ActionResult:
        p = proposal.params
        if proposal.kind == "rollback":
            message = self.shop.post("/actions/rollback", to=p["to"])["message"]
        elif proposal.kind == "restart":
            message = self.shop.post("/actions/restart", limit_mb=p.get("limit_mb"))["message"]
        elif proposal.kind == "set_pool":
            message = self.shop.post("/actions/set-pool", size=p["size"])["message"]
        else:
            return ActionResult(ok=False, applied=False, message="No safe automatic fix. Handing over to the on-call engineer.")
        time.sleep(self.verify_wait)
        # Judge the fix on the last few seconds, once things have settled: the first second after a fix still has the
        # old backlog draining. Samples from before the fix are excluded by only asking for the wait window.
        after = self.shop.get("/telemetry/metrics", minutes=self.verify_wait / 60) if self.verify_wait else []
        if not after:
            return ActionResult(ok=True, message=message)
        settled = after[-3:]
        errors, p95 = statistics.fmean(s["error_rate"] for s in settled), statistics.fmean(s["p95_ms"] for s in settled)
        healthy = errors < 0.05 and p95 < 200
        check = f"{len(settled)} s after the fix settled: 5xx rate {errors:.1%}, p95 {p95:.0f} ms."
        return ActionResult(ok=healthy, message=f"{message} {check}" + ("" if healthy else " The shop is still unhealthy."))
