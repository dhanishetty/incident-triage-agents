// What the triage agents read from Azure: a Log Analytics workspace and a workspace-based Application Insights.
// Nothing here is deployed by the project. Review it, then deploy it yourself (see README.md in this folder).

@description('Azure region')
param location string = resourceGroup().location

param workspaceName string = 'log-triage-demo'
param appInsightsName string = 'appi-triage-demo'

@description('Daily ingestion cap in GB, as text because Bicep has no decimals. When it is reached, ingestion stops for the day, so the bill cannot run away.')
param dailyCapGb string = '0.2'

@description('Days to keep data. 30 is included in the price of ingestion.')
@minValue(30)
param retentionDays int = 30

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionDays
    workspaceCapping: {
      dailyQuotaGb: json(dailyCapGb)
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

@description('Goes in AZURE_LOG_WORKSPACE_ID for the triage backend')
output workspaceId string = workspace.properties.customerId

@description('The id the triage reader identity needs the Log Analytics Reader role on')
output workspaceResourceId string = workspace.id

@description('Goes in APPLICATIONINSIGHTS_CONNECTION_STRING for the app that reports telemetry')
output connectionString string = appInsights.properties.ConnectionString
