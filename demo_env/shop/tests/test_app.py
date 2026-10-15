from fastapi.testclient import TestClient

from shop.app import create_app
from shop.service import Shop


def client():
    return TestClient(create_app(Shop(backend_url=None), autostart=False))


def test_inject_and_heal_over_http():
    c = client()
    assert c.get("/faults").json()["active"] == []
    assert c.post("/faults/bad-deploy").status_code == 202
    assert c.get("/faults").json()["active"] == ["bad-deploy"]
    assert c.get("/status").json()["version"] == "v482"
    assert c.post("/reset").json() == {"ok": True}
    assert c.get("/status").json()["faults"] == []


def test_unknown_fault_is_404():
    assert client().post("/faults/gremlins").status_code == 404


def test_telemetry_and_actions_over_http():
    c = client()
    c.post("/faults/bad-deploy")
    assert any(ch["meta"].get("version") == "v482" for ch in c.get("/telemetry/changes?hours=1").json())
    assert c.post("/actions/rollback?to=v481").json()["message"] == "Rolled back to v481."
    assert c.get("/status").json()["version"] == "v481"
    assert "pool size set to 8" in c.post("/actions/set-pool?size=8").json()["message"].lower()
    assert c.get("/telemetry/logs?minutes=1").json()
    assert c.get("/telemetry/metrics?minutes=1").json() == []
