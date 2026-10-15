import json
import time

import pytest
from fastapi.testclient import TestClient

from triage.api import create_app
from triage.deps import demo_deps


@pytest.fixture
def client():
    return TestClient(create_app(demo_deps(), step_delay=0))


def wait_status(client, run_id, status, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"never reached {status}: {body['status']}")


def start(client, scenario="bad-deploy"):
    r = client.post("/runs", json={"title": "demo", "resource": "demo", "labels": {"demo_scenario": scenario}})
    assert r.status_code == 202
    return r.json()["id"]


def test_health(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_full_run_through_the_api(client):
    run_id = start(client)
    wait_status(client, run_id, "awaiting_approval")
    assert client.post(f"/runs/{run_id}/approval", json={"decision": "approve"}).status_code == 202
    body = wait_status(client, run_id, "completed")
    assert body["events"][0]["seq"] == 1
    assert [e["seq"] for e in body["events"]] == list(range(1, len(body["events"]) + 1))
    assert [r["id"] for r in client.get("/runs").json()] == [run_id]


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/approval", json={"decision": "approve"}).status_code == 404


def test_deciding_twice_is_a_conflict(client):
    run_id = start(client, "memory-leak")
    wait_status(client, run_id, "awaiting_approval")
    client.post(f"/runs/{run_id}/approval", json={"decision": "reject"})
    assert client.post(f"/runs/{run_id}/approval", json={"decision": "approve"}).status_code == 409


def test_invalid_decision_is_rejected(client):
    run_id = start(client)
    wait_status(client, run_id, "awaiting_approval")
    assert client.post(f"/runs/{run_id}/approval", json={"decision": "maybe"}).status_code == 422


def test_event_stream_replays_the_run_and_ends(client):
    run_id = start(client, "memory-leak")
    wait_status(client, run_id, "awaiting_approval")
    client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})
    wait_status(client, run_id, "completed")
    with client.stream("GET", f"/runs/{run_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        data = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert data[-1]["kind"] == "run" and data[-1]["status"] == "completed"
    with client.stream("GET", f"/runs/{run_id}/events?after={len(data) - 1}") as r:
        tail = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert [e["seq"] for e in tail] == [data[-1]["seq"]]
