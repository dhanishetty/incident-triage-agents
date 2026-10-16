# Questions and answers


### Can we deploy this on AKS or Azure App Service?
Yes, both. Everything is already in standard Docker images.

| | Fit |
|---|---|
| **Container Apps** (recommended) | Simplest. Scales to zero, built-in HTTPS and managed identity. |
| **App Service** | Works for a demo. Frontend and backend as two web apps. |
| **AKS** | Works, but overkill for three small containers. |

---

### Once the application is deployed, how do I connect it to an Azure subscription and start using it?

| Step | What to do |
|---|---|
| 1. Identity | Turn on a managed identity for the backend (no passwords to store). |
| 2. Access | Give it two read-only roles: **Log Analytics Reader** on the workspace and **Reader** on the resource group to watch. |
| 3. Settings | Set `TRIAGE_MODE=azure`, `AZURE_LOG_WORKSPACE_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_APP_ROLE`, `TRIAGE_ALERT_TOKEN`. |
| 4. Telemetry | The app being watched must send its logs and metrics to Application Insights. |
| 5. Alert | Create an Azure Monitor alert rule whose Action Group webhook calls `https://<backend>/alerts?token=...` (common alert schema on). |
| 6. Use | When the alert fires, a run appears on the site. Review the diagnosis and approve or reject. |

Today it watches one subscription and resource group per deployment, and approved fixes are handed to a person (the Azure Action connector is not built yet).


---

### If deployed this way, can anyone from anywhere use the application?
No. As built it has almost no login, so it should not go on a public URL yet.

| Today | Risk if public |
|---|---|
| Website and `/runs` API are open | Anyone with the link can see incidents and their details. |
| `POST /runs` and the approval endpoint are open | Anyone can start a run or approve a fix. |
| Only `/alerts` needs a secret token | The token protects the webhook, not the rest. |
| One identity, one subscription per deployment | Visitors cannot connect their own subscription. They would only see yours. |

Before deploying publicly: add sign-in (for example Entra ID through Container Apps' built-in authentication), restrict who can approve to on-call engineers, and keep run creation and the demo shop off the public internet.


---

### How do all the components (the different agents) work together?
They do not talk to each other directly. All agents share one **state** (like a whiteboard), and a **graph** decides who goes next. Each agent reads what earlier ones wrote and adds its own piece.

| Agent | Reads from state | Writes to state |
|---|---|---|
| Triage supervisor | alert | plan |
| Metrics, Logs, Change (in parallel) | alert | one finding each |
| Diagnosis | all three findings | diagnosis (and may loop back to Logs) |
| Remediation | diagnosis | fix proposal |
| Approval gate | fix proposal | the person's decision |
| Action executor | approved fix | result |
| Postmortem | everything above | report and work item |

Helpers underneath: the **graph** (`graph.py`) sets the order, runs the evidence agents in parallel, runs the loop and pauses at the gate; **connectors** are the only way agents reach logs, metrics, deploys and fixes; the **reasoner** does the judgment. Each agent also emits events as it works, and the website animates them.


---

### What are the "graph" and LangGraph, in simple words?

| Term | Meaning |
|---|---|
| **Graph** | Not a chart. A **flowchart written as code**: boxes are the agents, arrows say who goes next. It lives in `graph.py` (about 50 lines). |
| **LangGraph** | The library that builds and runs that flowchart. We use it instead of writing the control logic ourselves. |

What LangGraph handles for us:
- **Shared state:** the "whiteboard" every agent reads from and writes to.
- **Parallel:** Logs, Metrics and Change start together.
- **Wait:** Diagnosis starts only when all three finish.
- **Loop:** if Diagnosis is unsure, go back to Logs, up to 2 times.
- **Pause and resume:** stop at the approval gate, save the state, and continue when a person decides.

The architecture diagram on the website is a drawing of the same flowchart.


---

### Do I have to know the architecture or libraries used in this project?
Only the ideas behind it, not every library.

| Level | What | Why |
|---|---|---|
| **Must know** | Multi-agent flow: shared state, parallel, loop | It is the heart of the project. |
| | Human approval before any change | Your main safety story. |
| | Connectors: agents never touch Azure directly | Lets the same agents run on the demo shop or Azure. |
| | **LangGraph** basics: nodes, edges, state, pause and resume | It runs the flow. |
| **Good to know** | Reasoner: rules or LLM, behind one interface, with guardrails | Questions about "is it really AI?" |
| | **FastAPI** and **Pydantic** | The API and the data shapes. |
| | **Docker** and compose | Running it locally. |
| **Skip unless asked** | React, Vite, Tailwind, nginx | It is the website only. |
| | Azure SDK details, KQL | Azure-specific plumbing. |


---

### What is the typical structure of an agent in this project?
Every agent is one function (a LangGraph "node") with the same five steps.

| Step | What it does | Example (Metrics agent) |
|---|---|---|
| 1. Read | Takes the shared state and rebuilds the data it needs | the `Alert` |
| 2. Announce | Marks itself "working" so the website animates it | `em.node("metrics", "working")` |
| 3. Act | Calls one dependency: a connector or the reasoner | `deps.metrics.query(alert)` |
| 4. Report | Posts what it found to the event log | `em.say(...)` |
| 5. Return | Hands back only its own piece of state | `{"findings": {"metrics": ...}}` |

```python
def metrics(state, config):
    em, alert = _em(config), Alert(**state["alert"])   # 1. read
    em.node("metrics", "working")                      # 2. announce
    evidence = deps.metrics.query(alert)               # 3. act
    em.say("Metrics agent", evidence.summary)          # 4. report
    return {"findings": {"metrics": ...}}              # 5. return
```

Agents never talk to Azure or a model directly. They go through `deps`, so the same agent runs on the demo shop or Azure. The three evidence agents share one helper, `gather()`, in `agents.py`. The gate and the executor follow the same pattern.


---

### Why do we need a reasoner, and is it the same as a connector?
No, they do different jobs.

| | Connector | Reasoner |
|---|---|---|
| **Job** | Gets facts from outside | Makes decisions from those facts |
| **Examples** | Read logs, read metrics, list deploys, apply a fix | Name the cause, say how sure, write the postmortem |
| **Talks to** | Azure or the demo shop | Rules, or an LLM |
| **Changes things?** | Only the Action connector, after approval | Never |

We need a reasoner because raw logs and numbers do not say "bad deploy, roll back to v481". Something has to weigh the evidence and decide; the agents themselves just pass data along. It is kept separate so rules can be swapped for an LLM without touching the agents or connectors.


---

### Why do we need a reasoner if the agents already decide?
In this project the agents do not decide. They are the workers, and the reasoner is the brain they call.

| | Agent | Reasoner |
|---|---|---|
| **Role** | Does a step: fetch, call, report | Makes the judgment |
| **Example** | Diagnosis agent: runs the step, updates state, posts events, loops if told to | `diagnose()`: weighs the evidence, returns a cause and confidence |

The Diagnosis agent just calls `reasoner.diagnose(...)` and acts on the answer.

Why split them: the agent code stays the same whether the judgment comes from rules or an LLM, and the judgment can be tested and scored on its own (`evals/score.py`). Decision logic could live inside each agent, but then swapping the model would mean rewriting the agents.
