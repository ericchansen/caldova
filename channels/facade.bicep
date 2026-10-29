targetScope = 'resourceGroup'

param image string
param hostedProjectEndpoint string
param mcpAudience string
param location string = 'eastus2'

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: 'caldova-environment'
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'caldova-mcp'
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: 'caldova${uniqueString(resourceGroup().id)}'
}
resource facade 'Microsoft.App/containerApps@2025-01-01' = {
  name: 'caldova-foundry-mcp'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {'${identity.id}': {}}
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {external: true, targetPort: 8000, transport: 'http', allowInsecure: false}
      registries: [{server: registry.properties.loginServer, identity: identity.id}]
    }
    template: {
      containers: [{
        name: 'facade'
        image: image
        resources: {cpu: json('0.5'), memory: '1Gi'}
        env: [
          {name: 'MCP_TENANT_ID', value: tenant().tenantId}
          {name: 'MCP_AUDIENCE', value: mcpAudience}
          {name: 'MCP_RESOURCE_URL', value: 'https://caldova-foundry-mcp.${environment.properties.defaultDomain}/mcp'}
          {name: 'HOSTED_PROJECT_ENDPOINT', value: hostedProjectEndpoint}
          {name: 'AZURE_CLIENT_ID', value: identity.properties.clientId}
        ]
        probes: [{
          type: 'Liveness'
          httpGet: {path: '/health', port: 8000}
          initialDelaySeconds: 10
          periodSeconds: 30
        }]
      }]
      scale: {minReplicas: 1, maxReplicas: 1}
    }
  }
}
output mcpEndpoint string = 'https://${facade.properties.configuration.ingress.fqdn}/mcp'
