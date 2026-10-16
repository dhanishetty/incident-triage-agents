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

### What does "graph" mean here, in simple words?
Not a chart. It is a **flowchart written as code**. The boxes are the agents and the arrows say who goes next.

It also handles the tricky parts: Logs, Metrics and Change start together (parallel); Diagnosis waits until all three finish; if Diagnosis is unsure it goes back to Logs, up to 2 times (loop); and the run stops at the approval gate until a person decides (pause).

It lives in `graph.py` (about 50 lines) and the library that runs it is LangGraph. The architecture diagram on the website is a drawing of the same flowchart.
