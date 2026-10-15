"""HTTP face of the demo environment.

  /orders                 place an order (the same handler the built-in load generator calls)
  /faults/{name}          break the shop on demand:  bad-deploy, memory-leak, db-pool   (POST), /reset heals it
  /telemetry/*            logs, metrics and changes, as the triage backend's connectors read them
  /actions/*              what the triage backend's Action connector calls once a person approves a fix
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from shop.service import Shop

FAULTS = ("bad-deploy", "memory-leak", "db-pool")


def create_app(shop: Shop | None = None, autostart: bool = True) -> FastAPI:
    shop = shop or Shop(backend_url=os.getenv("BACKEND_URL"), rps=float(os.getenv("SHOP_RPS", "25")))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if autostart:
            shop.t.log("INFO", "shop-api started", version=shop.version)
            shop.start()
        yield
        shop.stop()

    app = FastAPI(title="Shop demo environment", version="0.1.0", lifespan=lifespan)
    app.state.shop = shop

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/orders")
    def place_order() -> dict:
        status = shop.handle_order()
        if status >= 500:
            raise HTTPException(status, "order failed")
        return {"ok": True}

    @app.get("/status")
    def status() -> dict:
        return shop.status()

    # ---- fault injector ----
    @app.get("/faults")
    def faults() -> dict:
        return {"available": FAULTS, "active": sorted(shop.faults)}

    @app.post("/faults/{name}", status_code=202)
    def inject(name: str) -> dict:
        if name not in FAULTS:
            raise HTTPException(404, f"Unknown fault {name!r}. Available: {', '.join(FAULTS)}")
        shop.inject(name)
        return {"injected": name, "active": sorted(shop.faults)}

    @app.post("/reset")
    def reset() -> dict:
        shop.reset()
        return {"ok": True}

    # ---- telemetry (what Log Analytics, Azure Monitor and the Activity Log would serve) ----
    @app.get("/telemetry/logs")
    def logs(minutes: float = 30, level: str | None = None, limit: int = 2000) -> list[dict]:
        return shop.t.logs_since(minutes * 60, level, limit)

    @app.get("/telemetry/metrics")
    def metrics(minutes: float = 30) -> list[dict]:
        return shop.t.samples_since(minutes * 60)

    @app.get("/telemetry/changes")
    def changes(hours: float = 72) -> list[dict]:
        return shop.t.changes_since(hours * 3600)

    # ---- actions (called only after a person approves) ----
    @app.post("/actions/rollback")
    def rollback(to: str) -> dict:
        return {"message": shop.rollback(to)}

    @app.post("/actions/restart")
    def restart(limit_mb: int | None = None) -> dict:
        return {"message": shop.restart(limit_mb)}

    @app.post("/actions/set-pool")
    def set_pool(size: int) -> dict:
        return {"message": shop.set_pool(size)}

    return app
