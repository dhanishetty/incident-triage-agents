"""Connectors for the demo environment (demo_env/shop): they read its telemetry API and turn it into evidence.

Same job the Azure connectors will do against Log Analytics, Azure Monitor metrics and the Activity Log: fetch raw
telemetry, boil it down to a short summary a human (or an LLM) can read, and keep the numbers behind it in `detail`.
"""
from __future__ import annotations

import re
import statistics
import time
from typing import Callable

import httpx

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


def age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} hours"
    return f"{seconds / 86400:.0f} days"


def signature(msg: str) -> str:
    """Group log lines that differ only in numbers or quoted values, the way a log query's `summarize` would."""
    return re.sub(r"'[^']*'", "'…'", re.sub(r"\d+", "N", msg)).strip()


class EnvLogs:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def query(self, alert: Alert, *, deeper: bool = False) -> Evidence:
        now = self.shop.clock()
        errors = self.shop.get("/telemetry/logs", minutes=30, level="ERROR")
        if not errors:
            return Evidence(source="logs", summary="No errors in the last 30 minutes.", detail={"total": 0, "signatures": [], "deeper": deeper})

        groups: dict[str, dict] = {}
        for e in errors:
            g = groups.setdefault(signature(e["msg"]), {"count": 0, "first": e["ts"], "last": e["ts"], "sample": e})
            g["count"] += 1
            g["first"], g["last"] = min(g["first"], e["ts"]), max(g["last"], e["ts"])
        sigs = sorted(groups.items(), key=lambda kv: -kv[1]["count"])
        top_sig, top = sigs[0]
        top_msg = top["sample"]["msg"].split(": ", 1)[0] if "Timeout" not in top_sig else re.sub(r" \(size=.*", "", top["sample"]["msg"])

        summary = f"{len(errors)} errors in the last 30 minutes. Most common ({top['count']}x): {top_msg}. First seen {age(now - top['first'])} ago."
        detail: dict = {
            "total": len(errors),
            "signatures": [{"sig": s, "msg": g["sample"]["msg"], "count": g["count"], "first_age_s": now - g["first"], "last_age_s": now - g["last"]} for s, g in sigs[:5]],
            "deeper": deeper,
        }

        if deeper:
            top_errors = [e for e in errors if signature(e["msg"]) == top_sig]
            frames: dict[str, int] = {}
            for e in top_errors:
                if e.get("frames"):
                    frames[e["frames"][0]] = frames.get(e["frames"][0], 0) + 1
            detail["frames"] = sorted(frames.items(), key=lambda kv: -kv[1])
            extra = []
            if frames:
                f, n = detail["frames"][0]
                extra.append(f"The stack trace ends in {f} in {n} of the {len(top_errors)} errors." if n < len(top_errors) else f"The stack trace ends in {f} in all {n} of these errors.")
            pool = [re.search(r"size=(\d+), in use=(\d+)", e["msg"]) for e in top_errors]
            pool = [(int(m[1]), int(m[2])) for m in pool if m]
            if pool:
                full = sum(1 for size, used in pool if used >= size)
                detail["pool_saturated"] = full / len(pool) > 0.8
                extra.append(f"In {full} of {len(pool)} timeouts every pool connection (size {pool[0][0]}) was already in use.")
            if "OOMKilled" in top_sig and top["count"] > 1:
                gap = (top["last"] - top["first"]) / (top["count"] - 1)
                extra.append(f"The container was killed about every {age(gap)}.")
            summary += " " + " ".join(extra)
        return Evidence(source="logs", summary=summary, detail=detail)


class EnvMetrics:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def query(self, alert: Alert) -> Evidence:
        samples = self.shop.get("/telemetry/metrics", minutes=30)
        if len(samples) < 3:
            return Evidence(source="metrics", summary="Not enough metrics yet to say anything.", detail={})
        latest = samples[-1]["ts"]
        recent = samples[-10:]
        before = [s for s in samples if s["ts"] < latest - 45]  # samples from before the incident, when there are any

        def mean(rows, key):
            return statistics.fmean(r[key] for r in rows) if rows else None

        d = {
            "error_rate_now": mean(recent, "error_rate"),
            "error_rate_before": mean(before, "error_rate"),
            "p95_ms_now": mean(recent, "p95_ms"),
            "p95_ms_before": mean(before, "p95_ms"),
            "db_util": mean([dict(u=s["db_in_use"] / s["db_pool"]) for s in recent if s["db_pool"]], "u"),
            "db_pool": recent[-1]["db_pool"],
            "db_in_use": mean(recent, "db_in_use"),
            "restarts_last_minute": samples[-1]["restarts"] - samples[max(0, len(samples) - 60)]["restarts"],
            "mem_slope_mb_per_min": _mem_slope(samples[-60:]),
            "mem_mb_now": samples[-1]["mem_mb"],
        }

        facts = []
        if d["error_rate_now"] > 0.03:
            facts.append(f"HTTP 5xx rate is {d['error_rate_now']:.0%}" + (f" (was {d['error_rate_before']:.1%})" if d["error_rate_before"] is not None else ""))
        if d["p95_ms_now"] > 200:
            facts.append(f"p95 latency is {d['p95_ms_now']:.0f} ms" + (f" (was {d['p95_ms_before']:.0f} ms)" if d["p95_ms_before"] else ""))
        if d["restarts_last_minute"] > 0 or d["mem_slope_mb_per_min"] > 20:
            rate = d["mem_slope_mb_per_min"]
            rate_text = f"{rate / 60:.0f} MB per second" if rate >= 600 else f"{rate:.0f} MB per minute"
            facts.append(f"memory climbs about {rate_text} and the container restarted {d['restarts_last_minute']} times in the last minute")
        if d["db_util"] is not None and d["db_util"] >= 0.9:
            facts.append(f"the database pool is full ({d['db_in_use']:.0f} of {d['db_pool']} connections in use)")
        text = "; ".join(facts) + "."
        summary = text[0].upper() + text[1:] if facts else "All metrics look normal."
        return Evidence(source="metrics", summary=summary, detail=d)


def _mem_slope(samples: list[dict]) -> float:
    """MB per minute, measured inside the stretches between restarts so the sawtooth does not cancel itself out."""
    slopes, start = [], 0
    for i in range(1, len(samples) + 1):
        if i == len(samples) or samples[i]["mem_mb"] < samples[i - 1]["mem_mb"] - 1:
            seg = samples[start:i]
            if len(seg) >= 3 and seg[-1]["ts"] > seg[0]["ts"]:
                slopes.append((seg[-1]["mem_mb"] - seg[0]["mem_mb"]) / (seg[-1]["ts"] - seg[0]["ts"]) * 60)
            start = i
    return statistics.fmean(slopes) if slopes else 0.0


class EnvChanges:
    def __init__(self, shop: ShopClient) -> None:
        self.shop = shop

    def recent(self, alert: Alert) -> Evidence:
        now = self.shop.clock()
        changes = sorted(self.shop.get("/telemetry/changes", hours=72), key=lambda c: -c["ts"])
        if not changes:
            return Evidence(source="change", summary="No deploys or config changes in the last 3 days.", detail={"changes": []})
        rows = [{"kind": c["kind"], "age_min": (now - c["ts"]) / 60, "detail": c["detail"], "meta": c["meta"]} for c in changes]
        summary = " ".join(f"{r['detail']} ({age(r['age_min'] * 60)} ago)." for r in rows[:3])
        return Evidence(source="change", summary=summary, detail={"changes": rows})


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
            return ActionResult(ok=False, message="No safe automatic fix. Handing over to the on-call engineer.")
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
