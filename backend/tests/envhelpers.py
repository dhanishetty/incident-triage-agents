"""Serve a captured telemetry snapshot (tests/fixtures/*.json, taken from the real shop) as if it were the shop's API."""
import json
from pathlib import Path

import httpx

from triage.connectors.demo import DemoWorkItems
from triage.connectors.env import EnvActions, EnvChanges, EnvLogs, EnvMetrics, ShopClient
from triage.deps import Deps
from triage.llm.rules import RuleReasoner
from triage.models import Alert

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIOS = ["bad-deploy", "memory-leak", "db-pool"]


def snapshot(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def alert(title: str = "demo alert") -> Alert:
    return Alert(title=title, resource="shop-api (demo environment)", labels={"source": "demo-env"})


def shop_client(name: str) -> tuple[ShopClient, list[tuple[str, dict]]]:
    """A ShopClient whose 'server' is the snapshot. Writes (POSTs) are recorded in `calls`."""
    snap = snapshot(name)
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            calls.append((path, dict(request.url.params)))
            return httpx.Response(200, json={"message": {"/actions/rollback": f"Rolled back to {request.url.params.get('to')}.",
                                                        "/actions/restart": "Restarted.", "/actions/set-pool": "Pool size set."}[path]})
        if path == "/telemetry/logs":
            return httpx.Response(200, json=snap["logs"])
        if path == "/telemetry/metrics":
            return httpx.Response(200, json=snap["metrics"])
        if path == "/telemetry/changes":
            return httpx.Response(200, json=snap["changes"])
        return httpx.Response(404)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://shop")
    return ShopClient("http://shop", http=http, clock=lambda: snap["captured_at"]), calls


def env_deps_for(name: str) -> tuple[Deps, list]:
    shop, calls = shop_client(name)
    return Deps(EnvLogs(shop), EnvMetrics(shop), EnvChanges(shop), EnvActions(shop, verify_wait=0), DemoWorkItems(), RuleReasoner()), calls
