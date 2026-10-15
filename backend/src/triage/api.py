"""HTTP API: start runs, watch their events, approve or reject the proposed fix."""
from __future__ import annotations

import asyncio
import hmac
import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from triage.azure_alerts import from_common_alert_schema
from triage.deps import Deps, configured_env_deps, demo_deps
from triage.events import RunEvent
from triage.graph import build_graph
from triage.models import Alert
from triage.runs import NotAwaitingApproval, Run, RunManager


class Approval(BaseModel):
    decision: Literal["approve", "reject"]


class RunSummary(BaseModel):
    id: str
    status: str
    alert: Alert
    error: str | None = None


class RunDetail(RunSummary):
    events: list[RunEvent]


def _summary(run: Run) -> RunSummary:
    return RunSummary(id=run.id, status=run.status, alert=run.alert, error=run.error)


def create_app(deps: Deps | None = None, step_delay: float | None = None, env: Deps | None = None) -> FastAPI:
    deps = deps or demo_deps()
    env = env or configured_env_deps()
    if step_delay is None:
        step_delay = float(os.getenv("TRIAGE_STEP_DELAY", "0.6"))
    runs = RunManager(build_graph(deps), step_delay, build_graph(env) if env else None)
    app = FastAPI(title="Incident Triage Agents", version="0.1.0")
    app.state.runs = runs

    def find(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"No run {run_id}")
        return run

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/runs", status_code=202, response_model=RunSummary)
    def start_run(alert: Alert) -> RunSummary:
        """Start a run for an alert. The graph works in the background; watch /runs/{id}/events."""
        return _summary(runs.start(alert))

    @app.post("/alerts", status_code=202)
    def azure_alert(payload: dict, token: str | None = None) -> dict:
        """Where an Azure Monitor Action Group webhook posts (common alert schema). If TRIAGE_ALERT_TOKEN is set, the
        webhook URL must carry it as ?token=..., since this endpoint is meant to be reachable from the internet."""
        expected = os.getenv("TRIAGE_ALERT_TOKEN")
        if expected and not (token and hmac.compare_digest(token, expected)):
            raise HTTPException(401, "Missing or wrong token.")
        try:
            alert = from_common_alert_schema(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if alert is None:
            return {"ignored": "resolved"}  # a run is not needed when an alert clears
        return _summary(runs.start(alert)).model_dump()

    @app.get("/runs", response_model=list[RunSummary])
    def list_runs() -> list[RunSummary]:
        return [_summary(r) for r in runs.list()]

    @app.get("/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        run = find(run_id)
        return RunDetail(**_summary(run).model_dump(), events=run.events.after(0))

    @app.get("/runs/{run_id}/events")
    async def stream_events(run_id: str, after: int = 0) -> StreamingResponse:
        """Server-sent events: every event of the run, then the stream ends when the run does."""
        run = find(run_id)

        async def gen():
            seen = after
            while True:
                fresh = run.events.after(seen)
                for e in fresh:
                    yield f"id: {e.seq}\nevent: {e.kind}\ndata: {e.model_dump_json()}\n\n"
                    seen = e.seq
                if not fresh and run.status in ("completed", "failed"):
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/runs/{run_id}/approval", status_code=202, response_model=RunSummary)
    def decide(run_id: str, body: Approval) -> RunSummary:
        """The person at the approval gate decides. Only valid while the run is waiting."""
        find(run_id)
        try:
            return _summary(runs.decide(run_id, body.decision))
        except NotAwaitingApproval as exc:
            raise HTTPException(409, str(exc)) from exc

    return app
