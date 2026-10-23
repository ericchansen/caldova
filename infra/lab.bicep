param location string
param principalId string
param modelName string
param modelVersion string
param modelCapacity int
param mcpAudience string
param mcpImage string

var suffix = uniqueString(resourceGroup().id)
var accountName = 'caldova-${suffix}'

module foundry 'foundry.bicep' = {
  name: 'foundry'
  params: {
    location: location
    accountName: accountName
    principalId: principalId
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'caldova${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'caldova-mcp'
  location: location
}

resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'AcrPull')
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'caldova-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'caldova-environment'
  location: location
  properties: {
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource server 'Microsoft.App/containerApps@2025-01-01' = if (!empty(mcpImage)) {
  name: 'caldova-mcp'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'mcp'
        image: mcpImage
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'MCP_TENANT_ID', value: tenant().tenantId }
          { name: 'MCP_AUDIENCE', value: mcpAudience }
          { name: 'MCP_RESOURCE_URL', value: 'https://caldova-mcp.${environment.properties.defaultDomain}/mcp' }
        ]
        probes: [{
          type: 'Liveness'
          httpGet: { path: '/health', port: 8000 }
          initialDelaySeconds: 10
          periodSeconds: 30
        }]
      }]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
  dependsOn: [pullRole]
}

output accountName string = foundry.outputs.accountName
output projectEndpoint string = foundry.outputs.projectEndpoint
output registryEndpoint string = registry.properties.loginServer
output registryName string = registry.name
output mcpEndpoint string = 'https://caldova-mcp.${environment.properties.defaultDomain}/mcp'
output hostName string = 'caldova-mcp.${environment.properties.defaultDomain}'
