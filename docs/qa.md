# Questions and answers


### Can we deploy this on AKS or Azure App Service?
Yes, both. Everything is already in standard Docker images.

| | Fit |
|---|---|
| **Container Apps** (recommended) | Simplest. Scales to zero, built-in HTTPS and managed identity. |
| **App Service** | Works for a demo. Frontend and backend as two web apps. |
| **AKS** | Works, but overkill for three small containers. |

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


