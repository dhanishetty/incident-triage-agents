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
Think of each agent as a worker with the same short checklist. It is just one function (a LangGraph "node") that gets the shared state, does one job, and hands back its result. The five steps:

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

In plain words:
- **Read:** the agent looks at the shared whiteboard (the state) and picks up what it needs, such as the alert.
- **Announce:** it tells the website "I'm working on it", so the diagram lights up.
- **Act:** it asks for the one thing it is responsible for. The Metrics agent asks the metrics connector for numbers. The Diagnosis agent asks the reasoner to weigh the evidence.
- **Report:** it writes a short note about what it found, which appears in the event log.
- **Return:** it puts back only its own result. Because each agent writes only its own piece, three agents running at the same time never overwrite each other.

Agents never talk to Azure or a model directly. They go through `deps` (the connectors and the reasoner), so the same agent runs on the demo shop or on Azure without changes.

The three evidence agents share one helper, `gather()`, in `agents.py`, because they differ only in which connector they call. The others follow the same pattern with small differences: the approval gate pauses and waits for a person, and the executor is the only one that changes anything.


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


---

### How does the reasoner work?
It is one interface with four jobs: `plan`, `diagnose`, `propose_fix` and `postmortem`. The agents call these and don't care what is inside. There are two real versions you can pick with `TRIAGE_REASONER`:

| Version | How it decides |
|---|---|
| **Rules** (default) | Looks for a known pattern in the evidence and adds confidence for every signal that agrees. |
| **Azure OpenAI** | A model reads the evidence and answers in a fixed format. Its answer is checked before anyone acts on it. |

**Rules example (bad deploy):** errors in the logs add 0.30, a high 5xx rate adds 0.20, and a recent deploy adds 0.20. That is 0.70, below the 0.80 threshold, so it asks for a second Logs pass. A stack trace adds 0.15, giving 0.85, and it goes ahead.

**Azure OpenAI guardrails:**
- The model only diagnoses and writes the postmortem. It never picks an action.
- The fix comes from a fixed list of three (rollback, restart, set pool size).
- A version or pool size it names must appear in the change history, or it is dropped.
- Evidence goes in as quoted data, with an instruction not to obey it.
- If the call fails or is refused, the rules answer instead.


---

### How do the connectors work?
A connector is the only way an agent reaches the outside world. Agents depend on five small interfaces (in `connectors/base.py`), never on Azure itself.

| Interface | Job | Changes things? |
|---|---|---|
| `LogSource` | Find error patterns | No |
| `MetricSource` | Find spikes and saturation | No |
| `ChangeSource` | List deploys and config changes | No |
| `ActionRunner` | Apply an approved fix | **Yes**, and only after approval |
| `WorkItemSink` | File the postmortem | Writes a work item |

Each interface has three versions, chosen by `TRIAGE_MODE`:

| Mode | Where the data comes from |
|---|---|
| `demo` | Scripted data for the three demo incidents |
| `env` | The demo shop's own logs, metrics and change history |
| `azure` | Log Analytics (KQL queries) and the Azure Activity Log |

**What a connector does:** it only fetches rows and cleans them into a standard shape. The summary text and the numbers are then built by one shared module (`connectors/analysis.py`), so the demo shop and Azure produce the same kind of evidence and the same reasoner works on both. Parity tests prove it.

**Safety:** the read connectors need only read-only roles. Values that go into a KQL query come from configuration, never from an alert, and are validated. The Azure Action connector is not built yet, so in Azure mode an approved fix is handed to a person.


---

### Are the connectors in the code the same as the "Connector layer" in the diagram?
Yes. The five boxes in the diagram's Connector layer are the five interfaces in `connectors/base.py`.

| Diagram box | Code interface |
|---|---|
| Logs connector | `LogSource` |
| Metrics connector | `MetricSource` |
| Change connector | `ChangeSource` |
| Action connector | `ActionRunner` |
| Work item connector | `WorkItemSink` |

Two differences today: the diagram shows the Change connector reading Azure DevOps (Pipelines, Repos) as well as the Activity Log, but the code reads only the Activity Log. The diagram shows the Work item connector writing to Azure DevOps Boards, but the code uses an in-memory stand-in (`DemoWorkItems`). Both Azure DevOps parts are planned.
