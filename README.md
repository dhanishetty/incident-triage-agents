# Incident Triage Agents for Azure

A team of eight AI agents that triages an Azure incident. An Azure Monitor alert wakes a Triage supervisor, three evidence agents (Logs, Metrics, Change) query in parallel, a Diagnosis agent names the likely root cause, a Remediation agent proposes a fix, and a person approves before anything runs. A Postmortem agent files the report to Azure DevOps Boards either way.

![Architecture](docs/architecture.svg)

## Status

Early. The architecture and an animated replay of a simulated incident are built and run in Docker. The agent backend is not started. See [BLUEPRINT.md](BLUEPRINT.md) for the design, the agent roster and the build order.

| Part | State |
|---|---|
| Architecture page and **Play a run** replay (`frontend/`) | Running in Docker |
| Triage API, LangGraph agent graph, connectors, demo environment | Planned |

## Run it

Needs Docker.

```bash
docker compose up -d --build
```

Open http://localhost:8080 and press **Play a run**. Pick an incident, watch the agents work in parallel, then approve or reject the proposed fix at the gate.

Stop it with `docker compose down`.

## Develop the frontend

Needs Node 22.

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
npm run export:diagram # regenerate docs/architecture.svg from the diagram data
```

The diagram is defined in `frontend/src/features/architecture/diagrams.ts`, and the replay scripts are in `scenarios.ts` in the same folder.
