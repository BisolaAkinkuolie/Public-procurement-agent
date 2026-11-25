// Public Procurement Agent: private-by-default Azure deployment.
//
// Everything the agent talks to (Azure OpenAI, AI Search, Azure SQL) has public network access
// disabled and is reached through private endpoints from a VNet-integrated App Service. Auth is
// Microsoft Entra ID end to end: local/key auth is disabled and the web app's managed identity is
// granted least-privilege data-plane roles.
//
//   az deployment group create -g <rg> -f infra/main.bicep -p infra/main.parameters.json

targetScope = 'resourceGroup'

@description('Short prefix for resource names (3-10 lowercase letters/numbers).')
@minLength(3)
@maxLength(10)
param prefix string = 'cpa'

param location string = resourceGroup().location

@description('Container image for the API, e.g. ghcr.io/<you>/public-procurement-agent:latest')
param containerImage string

@description('Entra ID group that administers Azure SQL (object id and display name).')
param sqlAdminGroupObjectId string
param sqlAdminGroupName string

param chatModelName string = 'gpt-4o-mini'
param chatModelVersion string = '2024-07-18'
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'

var suffix = uniqueString(resourceGroup().id)
var names = {
  vnet: '${prefix}-vnet'
  logs: '${prefix}-logs-${suffix}'
  appi: '${prefix}-appi-${suffix}'
  openai: '${prefix}-aoai-${suffix}'
  search: '${prefix}-srch-${suffix}'
  sql: '${prefix}-sql-${suffix}'
  sqlDb: 'procurement'
  plan: '${prefix}-plan'
  app: '${prefix}-api-${suffix}'
}

// ---------------------------------------------------------------------------------------------
// Network: one subnet delegated to App Service for outbound VNet integration, one for private endpoints
// ---------------------------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: names.vnet
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      {
        name: 'snet-app'
        properties: {
          addressPrefix: '10.40.1.0/24'
          delegations: [{ name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: '10.40.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appi
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// ---------------------------------------------------------------------------------------------
// Azure OpenAI
// ---------------------------------------------------------------------------------------------
resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: names.openai
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: names.openai
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: { defaultAction: 'Deny' }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: chatModelName
  sku: { name: 'GlobalStandard', capacity: 50 }
  properties: { model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion } }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: embeddingModelName
  sku: { name: 'Standard', capacity: 50 }
  properties: { model: { format: 'OpenAI', name: embeddingModelName, version: embeddingModelVersion } }
  dependsOn: [chatDeployment] // deployments on one account must be created one at a time
}

// ---------------------------------------------------------------------------------------------
// Azure AI Search
// ---------------------------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: names.search
  location: location
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'disabled'
    disableLocalAuth: true
  }
}

// ---------------------------------------------------------------------------------------------
// Azure SQL (Entra-only authentication)
// ---------------------------------------------------------------------------------------------
resource sql 'Microsoft.Sql/servers@2021-11-01' = {
  name: names.sql
  location: location
  properties: {
    publicNetworkAccess: 'Disabled'
    minimalTlsVersion: '1.2'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      principalType: 'Group'
      login: sqlAdminGroupName
      sid: sqlAdminGroupObjectId
      tenantId: subscription().tenantId
    }
  }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2021-11-01' = {
  parent: sql
  name: names.sqlDb
  location: location
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 1 }
  properties: { autoPauseDelay: 60, minCapacity: json('0.5') }
}

// ---------------------------------------------------------------------------------------------
// Private endpoints + private DNS
// ---------------------------------------------------------------------------------------------
var privateLinks = [
  { name: 'openai', id: openai.id, group: 'account', zone: 'privatelink.openai.azure.com' }
  { name: 'search', id: search.id, group: 'searchService', zone: 'privatelink.search.windows.net' }
  #disable-next-line no-hardcoded-env-urls
  { name: 'sql', id: sql.id, group: 'sqlServer', zone: 'privatelink.database.windows.net' }
]

resource dnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [
  for link in privateLinks: {
    name: link.zone
    location: 'global'
  }
]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [
  for (link, i) in privateLinks: {
    parent: dnsZones[i]
    name: '${names.vnet}-link'
    location: 'global'
    properties: { virtualNetwork: { id: vnet.id }, registrationEnabled: false }
  }
]

resource endpoints 'Microsoft.Network/privateEndpoints@2023-11-01' = [
  for link in privateLinks: {
    name: '${prefix}-pe-${link.name}'
    location: location
    properties: {
      subnet: { id: vnet.properties.subnets[1].id }
      privateLinkServiceConnections: [
        { name: link.name, properties: { privateLinkServiceId: link.id, groupIds: [link.group] } }
      ]
    }
  }
]

resource dnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = [
  for (link, i) in privateLinks: {
    parent: endpoints[i]
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [{ name: link.name, properties: { privateDnsZoneId: dnsZones[i].id } }]
    }
  }
]

// ---------------------------------------------------------------------------------------------
// App Service (container) with managed identity and VNet integration
// ---------------------------------------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: names.plan
  location: location
  kind: 'linux'
  sku: { name: 'P0v3' }
  properties: { reserved: true }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: names.app
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: vnet.properties.subnets[0].id
    vnetRouteAllEnabled: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      healthCheckPath: '/health'
      appSettings: [
        { name: 'PA_MODE', value: 'azure' }
        { name: 'PA_AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
        { name: 'PA_AZURE_CHAT_DEPLOYMENT', value: chatDeployment.name }
        { name: 'PA_AZURE_EMBEDDING_DEPLOYMENT', value: embeddingDeployment.name }
        { name: 'PA_AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        {
          name: 'PA_DATABASE_URL'
          // Token auth via the app's managed identity; read-only intent. See infra/sql/agent_reader.sql.
          #disable-next-line no-hardcoded-env-urls
          value: 'mssql+pyodbc://@${sql.name}.database.windows.net/${names.sqlDb}?driver=ODBC+Driver+18+for+SQL+Server&Authentication=ActiveDirectoryMsi&ApplicationIntent=ReadOnly&Encrypt=yes'
        }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'WEBSITES_PORT', value: '8000' }
      ]
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Least-privilege data-plane roles for the app identity
// ---------------------------------------------------------------------------------------------
var roles = {
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
  searchIndexReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f' // Search Index Data Reader
}

resource openAiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openai
  name: guid(openai.id, app.id, roles.openAiUser)
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
  }
}

resource searchRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, app.id, roles.searchIndexReader)
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexReader)
  }
}

output appUrl string = 'https://${app.properties.defaultHostName}'
output appPrincipalName string = app.name
output openAiEndpoint string = openai.properties.endpoint
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output sqlServer string = sql.name
