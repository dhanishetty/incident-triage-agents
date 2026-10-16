# Questions and answers

A running record of questions asked while building this project, with the answers, plus questions likely to come up in a
demo. New entries go at the end of their section. For the design itself see [BLUEPRINT.md](../BLUEPRINT.md); for one
incident step by step see [sequence.md](sequence.md) and [the notebook](../notebooks/incident_walkthrough.ipynb).

## Asked during the build

### Is this an agentic "model" or agents?
Neither word is quite right. It is an agentic **application**: several agents (small programs with one job each) wired
together in a graph. A language model can sit inside it as the reasoning layer, but the project is the system around the
model: the connectors, the loop, the approval gate and the checks.

### Why incident triage and not stock analysis?
Stock analysis was set aside because it is hard to test (no ground truth to score against), depends on rate-limited
data, and tells a weaker story. Incident triage has real inputs (alerts, logs, metrics, deploys), a checkable answer
(did the fix heal the service?), and a natural place for human approval.

### Can the repo be private but still shared by link?
No. GitHub has no link-only visibility. Options are private plus invited collaborators, a public demo with private core
code, or going public with protections. The repo stays private for now; going public is a decision to make after the
backend works.

### How do I run it locally on Docker?
`docker compose up -d --build` from the repo root. The site is http://localhost:8080, the backend http://localhost:8010
and the demo shop http://localhost:8100. In the site, pick **Demo environment**, click a **Break** button, wait for the
alert (10 to 30 seconds), then approve the fix. `docker compose down` stops it.

### What does the Azure OpenAI reasoner do, and what is it not allowed to do?
It diagnoses (cause, confidence, whether it needs a deeper log pass) and writes the postmortem. It never chooses an
action: the fix comes from a fixed catalog keyed on the diagnosis kind. A version or pool size it names must appear in
the change history or it is dropped and the run escalates to a person. Evidence is passed as quoted data with an
instruction not to obey it. If the call fails or is refused, the rules-based reasoner answers instead. It has been tested
only against a scripted model; no real model has run it yet.

### What is Archify, and is it useful here?
An open-source AI skill that turns a description or a repo into an interactive architecture diagram. It would add little:
we already have a hand-built interactive diagram with a live run view, and the one extra we wanted, a sequence diagram,
is plain Mermaid. Not adopted.

### What is the structure of the agents?
Three layers. `graph.py` wires the steps, `agents.py` holds the steps (each does its job through `deps` and reports
progress as events), and `deps.py` holds the swappable parts: the read connectors, the action runner, the work-item sink
and the reasoner. State passes between agents as one dict. Swapping the demo shop for Azure, or rules for a model,
changes one line in `deps.py`. See the notebook for each agent's inputs and outputs.

### Why does the Logs agent appear next to the Metrics agent?
Logs, Metrics and Change run at the same time after Triage, because each reads a different source and Diagnosis needs all
three. No single one can say "bad deploy": metrics show the 5xx jump, logs show the error, and the change history shows
the deploy 40 seconds earlier. The notebook runs them one after another only so each can be read.

### Why does the Logs agent come a second time after Diagnosis?
Diagnosis was not sure (confidence 0.70, below the 0.80 threshold), so the graph sends it back to Logs for a second pass
with full stack traces. The new result replaces the first Logs finding, then Diagnosis runs again and reaches 0.85. The
loop is capped at 2 rounds. If Diagnosis is confident the first time (the memory leak case is), there is no second pass.
Only Logs gets a second pass, because stack traces live in the logs.

### What do the "Cell reference" headers in the notebook contain?
For each code cell: where it fits in the 9-step flow, the function, links to the code on GitHub, its purpose, its inputs
and its outputs. The links point at `main` by line number, so they can drift if a file changes; regenerating the notebook
fixes them. The repo is private, so the links open only when signed in as the owner.

### Can we deploy this on AKS or Azure App Service?
Yes, both. Everything is already in standard Docker images.

| | Fit |
|---|---|
| **Container Apps** (recommended) | Simplest. Scales to zero, built-in HTTPS and managed identity. |
| **App Service** | Works for a demo. Frontend and backend as two web apps. |
| **AKS** | Works, but overkill for three small containers. |

## Likely questions at a demo

### Is it really using an LLM?
By default no: the diagnosis is rules-based, which makes it fast, free and repeatable, and it is the baseline the model
is scored against. The Azure OpenAI reasoner is built behind the same interface (`TRIAGE_REASONER=openai`) and is
scripted-tested. `backend/evals/score.py` is how to measure it once a model is deployed.

### What stops it from doing something dangerous?
Four things. The only code that changes a resource is the Action connector. It runs only after a person approves at the
approval gate, which is a real pause in the graph. The fix is chosen from a fixed catalog of three, never invented. And
the read connectors need only read-only roles.

### Does it run on Azure today?
Not yet. The Azure connectors (Log Analytics queries, Activity Log) and the alert webhook are written and tested against
fakes and captured data, but they have not met real Azure data, so the query and column names are unproven. Nothing is
deployed. The Azure Action connector is not built, so in Azure mode an approved fix is reported as "not applied" and
handed to a person.

### What happens if the fix does not work?
The executor checks the system after applying the fix. If it is still unhealthy, the run says so, hands over to the
on-call engineer, and the postmortem records that. A rejected fix leaves the system as it was.

### How do you know the Azure path gives the same answers as the demo path?
Parity tests feed identical captured telemetry through both and require identical evidence. They caught one real bug,
where Azure returns whole numbers as floats and a summary said "restarted 5.0 times".
