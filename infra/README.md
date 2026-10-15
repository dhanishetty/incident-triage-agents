# Azure setup for the triage agents

`main.bicep` defines what the agents read from Azure. **Nothing here is deployed by the project.** You run these
commands, so you decide the account, region and resource group.

## What it creates

| Resource | Purpose |
|---|---|
| Log Analytics workspace `log-triage-demo` | Where telemetry lands and where the Logs and Metrics connectors query it |
| Application Insights `appi-triage-demo` | Workspace-based. The app reports requests, errors and gauges here |

The Change connector reads the resource group's **Activity Log**, which needs no resources of its own.

## Cost

Both resources bill as Log Analytics ingestion. The Bicep sets a **daily cap of 0.2 GB**: when it is reached,
ingestion stops for the day, so the bill cannot run away. That is at most about 6 GB a month. The first 5 GB a
month are free on the pay-as-you-go tier, so the worst case is a few dollars. Check current prices for your
region before you rely on this. Nothing else here has a standing cost.

The cap also bounds what the app may send: the demo shop should report about 5% of its requests, all its errors
and a few gauges, which stays well inside it.

## Deploy

Use your personal subscription. Check which account you are on first:

```bash
az account show --query "{user:user.name, subscription:name}" -o table   # expect dhanishetty@gmail.com
az group create --name rg-triage-demo --location <your region>
az deployment group create --resource-group rg-triage-demo --template-file infra/main.bicep
```

The deployment prints three outputs: `workspaceId`, `workspaceResourceId` and `connectionString`.

## A read-only identity for the agents

The connectors only read. Give them a service principal with exactly two roles:

```bash
az ad sp create-for-rbac --name triage-reader --skip-assignment           # note appId, password, tenant
az role assignment create --assignee <appId> --role "Log Analytics Reader" --scope <workspaceResourceId>
az role assignment create --assignee <appId> --role "Reader" \
  --scope /subscriptions/<subscription id>/resourceGroups/rg-triage-demo
```

Then run the backend with:

```
TRIAGE_MODE=azure
AZURE_LOG_WORKSPACE_ID=<workspaceId>
AZURE_SUBSCRIPTION_ID=<subscription id>
AZURE_RESOURCE_GROUP=rg-triage-demo
AZURE_APP_ROLE=shop-api                 # the cloud role name the app reports under
AZURE_CLIENT_ID=<appId>  AZURE_TENANT_ID=<tenant>  AZURE_CLIENT_SECRET=<password>
TRIAGE_ALERT_TOKEN=<a long random string>   # the Action Group webhook must send it as ?token=
```

Keep those values in an env file that is not committed.

## Alerts

An Azure Monitor alert rule fires an Action Group, whose webhook posts to the backend's `/alerts` endpoint:
`https://<backend host>/alerts?token=<TRIAGE_ALERT_TOKEN>`. Turn on the **common alert schema** for that webhook.
The backend must be reachable from the internet for this, which comes with deployment.

## Tear it all down

```bash
az group delete --name rg-triage-demo --yes
az ad sp delete --id <appId>
```
