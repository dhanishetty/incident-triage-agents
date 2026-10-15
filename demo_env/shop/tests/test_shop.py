"""The faults must come from real behaviour. These tests drive the handler directly and read the telemetry it produces."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from shop.service import BAD_VERSION, HEALTHY_VERSION, Shop, breached


def drive(shop: Shop, orders: int = 60, workers: int = 8) -> dict:
    """Place orders concurrently, then turn them into one metrics sample."""
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda _: shop.handle_order(), range(orders)))
    return shop.sample_now()


@pytest.fixture
def shop():
    return Shop(backend_url=None)


def test_a_healthy_shop_has_almost_no_errors(shop):
    s = drive(shop)
    assert s["error_rate"] < 0.02
    assert s["p95_ms"] < 150


def test_bad_deploy_makes_orders_fail_and_logs_the_exception(shop):
    shop.inject("bad-deploy")
    s = drive(shop, orders=100)
    assert 0.15 < s["error_rate"] < 0.5
    errors = shop.t.logs_since(60, "ERROR")
    assert errors and all("PricingCalculator.apply_discount" in e["msg"] for e in errors)
    assert errors[0]["frames"][0] == "pricing.py:apply_discount"
    deploys = [c for c in shop.t.changes if c["kind"] == "deploy" and c["meta"].get("version") == BAD_VERSION]
    assert deploys, "the bad deploy must appear in the change history"


def test_rollback_heals_a_bad_deploy(shop):
    shop.inject("bad-deploy")
    drive(shop, orders=60)
    shop.rollback(HEALTHY_VERSION)
    assert drive(shop, orders=100)["error_rate"] < 0.02


def test_small_pool_causes_timeouts_and_slow_orders(shop):
    shop.inject("db-pool")
    s = drive(shop, orders=80, workers=16)
    assert s["error_rate"] > 0.1
    assert s["p95_ms"] > 200
    assert any("Timeout waiting for a database connection" in e["msg"] for e in shop.t.logs_since(60, "ERROR"))
    change = next(c for c in shop.t.changes if c["meta"].get("setting") == "pool_size" and c["meta"].get("to") == 1)
    assert time.time() - change["ts"] > 24 * 3600  # recorded as an old change


def test_restoring_the_pool_heals_it(shop):
    shop.inject("db-pool")
    shop.set_pool(8)
    assert drive(shop, orders=80, workers=16)["error_rate"] < 0.02


def test_memory_leak_gets_the_container_killed_repeatedly(shop):
    shop.inject("memory-leak")
    for _ in range(4):  # one kill every ~180 orders (4 MB each over a 724 MB headroom)
        drive(shop, orders=120)
    assert shop.restarts >= 2
    assert any("OOMKilled" in e["msg"] for e in shop.t.logs_since(60, "ERROR"))
    assert not [c for c in shop.t.changes_since(48 * 3600) if c["kind"] == "deploy"]  # no deploy explains it


def test_restart_with_a_higher_limit_gives_the_leak_more_room(shop):
    shop.inject("memory-leak")
    shop.restart(limit_mb=2048)
    for _ in range(2):
        drive(shop, orders=120)
    assert shop.restarts == 0


def test_reset_restores_the_baseline(shop):
    shop.inject("bad-deploy")
    shop.inject("db-pool")
    shop.reset()
    assert shop.version == HEALTHY_VERSION and shop.faults == set() and shop.pool.size == 8
    assert drive(shop)["error_rate"] < 0.02


def sample(**kw):
    return {"ts": time.time(), "rps": 25, "error_rate": 0.0, "p95_ms": 40.0, "mem_mb": 300.0, "restarts": 0, "db_in_use": 2, "db_pool": 8, **kw}


def test_alert_rules():
    assert breached([sample() for _ in range(10)]) == []
    assert [r.id for r in breached([sample(error_rate=0.3) for _ in range(8)])] == ["errors"]
    assert [r.id for r in breached([sample(p95_ms=300) for _ in range(8)])] == ["latency"]
    assert [r.id for r in breached([sample(restarts=0), sample(restarts=2)])] == ["restarts"]
    assert breached([sample(error_rate=0.3) for _ in range(7)]) == []  # not long enough yet


def test_an_alert_is_delivered_to_the_backend_once(monkeypatch):
    posted = []

    class Resp:
        is_success = True

        def json(self):
            return {"id": "run-1"}

    monkeypatch.setattr("shop.service.httpx.post", lambda url, json, timeout: posted.append((url, json)) or Resp())
    shop = Shop(backend_url="http://backend:8000")
    for _ in range(8):
        shop.t.add_sample(sample(error_rate=0.3))
    assert [r.id for r in shop.evaluate_alerts()] == ["errors"]
    assert shop.evaluate_alerts() == []  # still breached, but already reported
    assert len(posted) == 1
    url, body = posted[0]
    assert url == "http://backend:8000/runs"
    assert body["labels"]["rule"] == "errors" and body["resource"].startswith("shop-api")
    assert shop.alerts_fired[0]["run_id"] == "run-1"
