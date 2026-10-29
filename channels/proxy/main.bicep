targetScope = 'resourceGroup'

param image string
param tenantId string
param environmentName string
param registryName string
param foundryAccountName string
param foundryProjectName string
param projectEndpoint string
param agentName string
var prefix = 'caldova-sdk-proxy'

resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  name: '${foundryAccountName}/${foundryProjectName}'
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: prefix
  location: 'eastus2'
  tags: { experiment: 'path4-sdk-proxy' }
}
resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
// Data-plane access scoped to the one existing lab project, not the account/RG.
resource invoke 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, identity.id, 'Cognitive Services User')
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: prefix
  location: 'eastus2'
  tags: { experiment: 'path4-sdk-proxy' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 3978, transport: 'http', allowInsecure: false }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'proxy'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'PROXY_CLIENT_ID', value: identity.properties.clientId }
          { name: 'PROXY_TENANT_ID', value: tenantId }
          { name: 'PROXY_PROJECT_ENDPOINT', value: projectEndpoint }
          { name: 'PROXY_AGENT_NAME', value: agentName }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [pull, invoke]
}
resource bot 'Microsoft.BotService/botServices@2022-09-15' = {
  name: prefix
  location: 'global'
  kind: 'azurebot'
  sku: { name: 'F0' }
  tags: { experiment: 'path4-sdk-proxy' }
  properties: {
    displayName: 'Caldova SDK Proxy Lab'
    endpoint: 'https://${app.properties.configuration.ingress.fqdn}/api/messages'
    msaAppId: identity.properties.clientId
    msaAppTenantId: tenantId
    msaAppType: 'UserAssignedMSI'
    msaAppMSIResourceId: identity.id
    publicNetworkAccess: 'Enabled'
  }
}
resource teams 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: bot
  name: 'MsTeamsChannel'
  location: 'global'
  properties: { channelName: 'MsTeamsChannel', properties: { isEnabled: true } }
}
resource directline 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: bot
  name: 'DirectLineChannel'
  location: 'global'
  properties: {
    channelName: 'DirectLineChannel'
    properties: {
      sites: [{
        siteName: 'proxy-runtime-smoke'
        isEnabled: true
        isV1Enabled: false
        isV3Enabled: true
      }]
    }
  }
}
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
output identityId string = identity.id
output botId string = bot.id
output endpoint string = 'https://${app.properties.configuration.ingress.fqdn}/api/messages'
