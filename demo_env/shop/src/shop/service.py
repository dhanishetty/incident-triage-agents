"""The sample service, its load, its fault injector and its alert rules.

`Shop.handle_order` is a real request handler: it prices an order, takes a database connection from a bounded pool,
and can fail. The faults change how it behaves, so the telemetry comes from real failures, not from a script:

  bad-deploy   releases v482, whose pricing code crashes when an order has no coupon
  memory-leak  every order leaks memory until the container is killed for exceeding its limit
  db-pool      a config change shrinks the database pool, so orders queue and time out

(Memory is accounted in a counter rather than really allocated, so the demo is safe to run anywhere.)
"""
from __future__ import annotations

import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from shop.telemetry import Telemetry

SERVICE = "shop-api (demo environment)"
HEALTHY_VERSION = "v481"
BAD_VERSION = "v482"
MEM_BASE_MB = 300.0
LEAK_MB_PER_ORDER = 4.0
POOL_WAIT_S = 0.25


class Coupon:
    discount = 0.1


class PoolTimeout(Exception):
    pass


class Pool:
    """A bounded database connection pool, so a small pool really does make orders wait."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.in_use = 0
        self._cond = threading.Condition()

    def acquire(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        with self._cond:
            while self.in_use >= self.size:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            self.in_use += 1
            return True

    def release(self) -> None:
        with self._cond:
            self.in_use -= 1
            self._cond.notify()

    def resize(self, size: int) -> None:
        with self._cond:
            self.size = size
            self._cond.notify_all()


@dataclass(frozen=True)
class AlertRule:
    id: str
    title: str
    severity: str


RULES = {
    "errors": AlertRule("errors", "shop-api 5xx error rate above 5% for 8 seconds", "high"),
    "latency": AlertRule("latency", "shop-api p95 latency above 200 ms for 8 seconds", "high"),
    "restarts": AlertRule("restarts", "shop-api restarted 2 or more times in one minute", "critical"),
}


def breached(samples: list[dict]) -> list[AlertRule]:
    """Which alert rules the recent samples breach. Pure, so it is easy to test."""
    out: list[AlertRule] = []
    recent = samples[-8:]
    if len(recent) == 8 and all(s["error_rate"] > 0.05 for s in recent):
        out.append(RULES["errors"])
    if len(recent) == 8 and all(s["p95_ms"] > 200 for s in recent):
        out.append(RULES["latency"])
    minute = samples[-60:]
    if len(minute) >= 2 and minute[-1]["restarts"] - minute[0]["restarts"] >= 2:
        out.append(RULES["restarts"])
    return out


class Shop:
    def __init__(self, backend_url: str | None = None, rps: float = 25.0) -> None:
        self.t = Telemetry()
        self.backend_url = backend_url
        self.rps = rps
        self.pool = Pool(8)
        self.version = HEALTHY_VERSION
        self.mem_mb = MEM_BASE_MB
        self.mem_limit_mb = 1024
        self.restarts = 0
        self.leaking = False
        self.faults: set[str] = set()
        self.alerts_fired: list[dict] = []
        self._bucket: list[tuple[int, float]] = []  # (http status, latency ms) of this second's orders
        self._lock = threading.Lock()
        self._active_rules: set[str] = set()
        self._last_fired: dict[str, float] = {}
        self._stop = threading.Event()
        self._baseline()

    # ---- baseline and reset -------------------------------------------------------------------------------

    def _baseline(self) -> None:
        day = 86400
        self.t.change("deploy", f"Deploy {HEALTHY_VERSION}: checkout and pricing updates", ts=time.time() - 6 * day, version=HEALTHY_VERSION)
        self.t.change("config", "Database pool_size set to 8", ts=time.time() - 9 * day, setting="pool_size", to=8)

    def reset(self) -> None:
        self.faults.clear()
        self.version = HEALTHY_VERSION
        self.pool.resize(8)
        self.mem_mb, self.mem_limit_mb, self.restarts, self.leaking = MEM_BASE_MB, 1024, 0, False
        self._active_rules.clear()
        self._last_fired.clear()
        self.alerts_fired.clear()
        self._bucket.clear()
        self.t.clear()
        self._baseline()
        self.t.log("INFO", "Environment reset to healthy baseline", version=self.version)

    # ---- the request handler ------------------------------------------------------------------------------

    def handle_order(self) -> int:
        start = time.perf_counter()
        status = 200
        try:
            self._price()
            self._query_database()
            if self.leaking:
                self._leak()
        except PoolTimeout:
            status = 503
            self.t.log(
                "ERROR",
                f"Timeout waiting for a database connection from the pool (size={self.pool.size}, in use={self.pool.in_use})",
                version=self.version,
                frames=["db.py:acquire_connection", "orders.py:create_order"],
            )
        except AttributeError as exc:
            status = 500
            self.t.log(
                "ERROR",
                f"AttributeError in PricingCalculator.apply_discount: {exc}",
                version=self.version,
                frames=["pricing.py:apply_discount", "orders.py:create_order"],
            )
        latency = (time.perf_counter() - start) * 1000
        with self._lock:
            self._bucket.append((status, latency))
        if status == 200 and random.random() < 0.02:
            self.t.log("INFO", "Order created", version=self.version)
        return status

    def _price(self) -> None:
        time.sleep(random.uniform(0.005, 0.015))
        if self.version == BAD_VERSION:
            coupon = None if random.random() < 0.3 else Coupon()  # v482 assumes every order has a coupon
            _ = coupon.discount  # type: ignore[union-attr]  # raises AttributeError when there is no coupon

    def _query_database(self) -> None:
        if not self.pool.acquire(POOL_WAIT_S):
            raise PoolTimeout
        try:
            time.sleep(random.uniform(0.06, 0.10))
        finally:
            self.pool.release()

    def _leak(self) -> None:
        with self._lock:
            self.mem_mb += LEAK_MB_PER_ORDER
            if self.mem_mb <= self.mem_limit_mb:
                return
            self.mem_mb = MEM_BASE_MB
            self.restarts += 1
        self.t.log("ERROR", f"Container shop-api OOMKilled (memory limit {self.mem_limit_mb} MB)", version=self.version, frames=["kernel:oom_kill"])

    # ---- metrics ------------------------------------------------------------------------------------------

    def sample_now(self) -> dict:
        """Turn the last second of orders into one metrics sample."""
        with self._lock:
            bucket, self._bucket = self._bucket, []
            mem, restarts = self.mem_mb, self.restarts
        n = len(bucket)
        errors = sum(1 for s, _ in bucket if s >= 500)
        lat = sorted(l for _, l in bucket)
        sample = {
            "ts": time.time(),
            "rps": n,
            "error_rate": round(errors / n, 4) if n else 0.0,
            "p95_ms": round(lat[min(n - 1, int(n * 0.95))], 1) if n else 0.0,
            "mem_mb": round(mem, 1),
            "restarts": restarts,
            "db_in_use": self.pool.in_use,
            "db_pool": self.pool.size,
        }
        self.t.add_sample(sample)
        return sample

    # ---- faults and actions -------------------------------------------------------------------------------

    def inject(self, name: str) -> None:
        if name == "bad-deploy":
            self.version = BAD_VERSION
            self.t.change("deploy", f"Deploy {BAD_VERSION}: new coupon discount rules in the pricing module", version=BAD_VERSION, from_version=HEALTHY_VERSION)
        elif name == "memory-leak":
            self.leaking = True  # no deploy or config change: the leak was already in the running build
        elif name == "db-pool":
            self.pool.resize(1)
            # the change is recorded as made 40 hours ago: it only hurts now, under today's traffic
            self.t.change("config", "Database pool_size lowered from 8 to 1", ts=time.time() - 40 * 3600, setting="pool_size", from_=8, to=1)
        else:
            raise KeyError(name)
        self.faults.add(name)
        self.t.log("INFO", f"Fault injected: {name}", version=self.version)

    def rollback(self, version: str) -> str:
        self.version = version
        self.faults.discard("bad-deploy")
        self.t.change("deploy", f"Rollback to {version}", version=version, rollback=True)
        self.t.log("INFO", f"Rolled back to {version}", version=version)
        return f"Rolled back to {version}."

    def restart(self, limit_mb: int | None = None) -> str:
        with self._lock:
            self.mem_mb = MEM_BASE_MB
            if limit_mb:
                self.mem_limit_mb = limit_mb
        self.t.change("config", f"Restarted; memory limit {self.mem_limit_mb} MB", setting="memory_limit_mb", to=self.mem_limit_mb)
        self.t.log("INFO", "Container restarted", version=self.version)
        return f"Restarted; memory limit is now {self.mem_limit_mb} MB. The leak itself is still in the build."

    def set_pool(self, size: int) -> str:
        self.pool.resize(size)
        self.faults.discard("db-pool")
        self.t.change("config", f"Database pool_size set to {size}", setting="pool_size", to=size)
        self.t.log("INFO", f"Pool size set to {size}", version=self.version)
        return f"Database pool size set to {size}."

    # ---- background loops ---------------------------------------------------------------------------------

    def start(self) -> None:
        for fn in (self._load_loop, self._sample_loop, self._alert_loop):
            threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    def stop(self) -> None:
        self._stop.set()

    def _load_loop(self) -> None:
        with ThreadPoolExecutor(max_workers=64) as pool:
            while not self._stop.is_set():
                pool.submit(self.handle_order)
                time.sleep(1 / self.rps)

    def _sample_loop(self) -> None:
        while not self._stop.wait(1.0):
            self.sample_now()

    def _alert_loop(self) -> None:
        while not self._stop.wait(2.0):
            self.evaluate_alerts()

    def evaluate_alerts(self) -> list[AlertRule]:
        """Fire an alert (a webhook to the triage backend) when a rule starts being breached."""
        with self.t._lock:
            samples = list(self.t.samples)
        now = time.time()
        active = breached(samples)
        ids = {r.id for r in active}
        fired = []
        for rule in active:
            if rule.id not in self._active_rules and now - self._last_fired.get(rule.id, 0) > 60:
                self._last_fired[rule.id] = now
                self._fire(rule)
                fired.append(rule)
        self._active_rules = ids
        return fired

    def _fire(self, rule: AlertRule) -> None:
        payload = {
            "id": f"{rule.id}-{int(time.time())}",
            "title": rule.title,
            "resource": SERVICE,
            "severity": rule.severity,
            "labels": {"rule": rule.id, "source": "demo-env", "fired_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        }
        record = {"rule": rule.id, "title": rule.title, "ts": time.time(), "run_id": None, "delivered": False}
        self.alerts_fired.append(record)
        self.t.log("WARN", f"Alert fired: {rule.title}", version=self.version)
        if not self.backend_url:
            return
        try:
            r = httpx.post(f"{self.backend_url}/runs", json=payload, timeout=5)
            record.update(delivered=r.is_success, run_id=r.json().get("id") if r.is_success else None)
        except httpx.HTTPError as exc:
            self.t.log("WARN", f"Could not deliver alert to the triage backend: {exc}", version=self.version)

    # ---- a summary for the UI -----------------------------------------------------------------------------

    def status(self) -> dict:
        with self.t._lock:
            latest = self.t.samples[-1] if self.t.samples else None
        recent = self.t.samples_since(10)
        return {
            "version": self.version,
            "faults": sorted(self.faults),
            "latest": latest,
            "error_rate_10s": round(statistics.fmean(s["error_rate"] for s in recent), 4) if recent else 0.0,
            "p95_ms_10s": round(statistics.fmean(s["p95_ms"] for s in recent), 1) if recent else 0.0,
            "alerts": self.alerts_fired[-5:],
        }
