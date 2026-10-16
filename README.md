# Incident Triage Agents for Azure

A team of eight AI agents that triages an Azure incident. An Azure Monitor alert wakes a Triage supervisor, three evidence agents (Logs, Metrics, Change) query in parallel, a Diagnosis agent names the likely root cause, a Remediation agent proposes a fix, and a person approves before anything runs. A Postmortem agent files the report to Azure DevOps Boards either way.

![Architecture](docs/architecture.svg)

One incident from alert to closed run: [docs/sequence.md](docs/sequence.md). To step through it function by function: [notebooks/incident_walkthrough.ipynb](notebooks/incident_walkthrough.ipynb).

## Status

Early. The agent graph runs end to end. In **demo environment** mode the agents investigate a real service that you break on demand, reading its actual logs, metrics and change history, and a fix they apply really heals it. The reasoning there is rules-based by default; an Azure OpenAI reasoner (`TRIAGE_REASONER=openai`) is built and tested against a scripted model. The Azure connectors and that reasoner are tested against fakes; running them on a real subscription is next. See [BLUEPRINT.md](BLUEPRINT.md) for the design, the agent roster and the build order.

| Part | State |
|---|---|
| Architecture page with **Play a run**: a simulated replay, or a live run on the backend (`frontend/`) | Running in Docker |
| LangGraph agent graph, approval pause, event stream, API (`backend/`) | Running in Docker, 86 tests |
| Demo environment (`demo_env/shop/`): a sample service, fault injector, alert rule and telemetry API | Running in Docker, 13 tests |
| Environment connectors and a rules-based reasoner that diagnoses from real telemetry | Running in Docker |
| Azure OpenAI reasoner (guard-railed, falls back to rules), scored by `backend/evals/score.py` | Built, tested with a scripted model |
| Connector interfaces | Defined; demo, environment and Azure implementations |
| Azure connectors (Logs, Metrics, Change) and the Azure Monitor `/alerts` webhook | Built and tested against fakes of the Azure SDK. Not yet run against a real subscription |
| Running on real Azure (infra is defined in `infra/`, not deployed), Azure Action connector, trying the OpenAI reasoner on a real model | Planned |

## Run it

Needs Docker.

```bash
docker compose up -d --build
```

- http://localhost:8080 is the site. Press **Play a run** for a simulated replay, or switch to **Live backend** and press **Start live run** to watch the real agent graph run on the server. Switch to **Demo environment**, press a **Break** button, and watch the shop's own alert start a run. Approve or reject at the gate in any mode.
- http://localhost:8010/docs is the API. Start a real run (demo data) and watch it:

```bash
curl -X POST localhost:8010/runs -H 'content-type: application/json' \
  -d '{"title":"orders-api latency","resource":"orders-api","labels":{"demo_scenario":"bad-deploy"}}'
curl -N localhost:8010/runs/<id>/events                 # server-sent events
curl -X POST localhost:8010/runs/<id>/approval -H 'content-type: application/json' -d '{"decision":"approve"}'
```

- http://localhost:8100/docs is the demo environment (the shop). Break it, and its alert rule starts a run on the backend by itself:

```bash
curl -X POST localhost:8100/faults/bad-deploy      # or memory-leak, db-pool
curl localhost:8010/runs                           # a run appears within ~10-30 s
curl -X POST localhost:8100/reset                  # back to healthy
```

Runs that name a `demo_scenario` label (`bad-deploy`, `memory-leak`, `db-connections`) replay a scripted scenario. Any other alert is investigated from the shop's real telemetry. Either way the run pauses at the approval gate until you approve or reject.

Stop it with `docker compose down`.

## Test

```bash
docker run --rm -v "$PWD":/repo -w /repo/backend python:3.12-slim \
  sh -c "pip install -q -e '.[dev]' && python -m pytest -q"
# the demo environment (about 15 s): same command with -w /repo/demo_env/shop
```

The tests check each scenario and the loop back for more evidence, that the three evidence agents truly run in parallel, that a reject changes nothing, and that every node and link the backend emits exists in the frontend diagram.

## Develop the frontend

Needs Node 22.

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
npm run export:diagram # regenerate docs/architecture.svg from the diagram data
```

The diagram is defined in `frontend/src/features/architecture/diagrams.ts`, and the replay scripts are in `scenarios.ts` in the same folder.
