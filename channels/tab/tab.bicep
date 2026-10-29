targetScope = 'resourceGroup'
param image string
param appId string
param hostedProjectEndpoint string
param diagnosticClient string = ''
param location string = 'eastus2'
param environmentName string
param identityName string
param registryName string
param tabName string
param sandboxName string

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}
var hostOrigin = 'https://${tabName}.${environment.properties.defaultDomain}'
var sandboxOrigin = 'https://${sandboxName}.${environment.properties.defaultDomain}'
resource apps 'Microsoft.App/containerApps@2025-01-01' = [for mode in ['host', 'sandbox']: {
  name: mode == 'host' ? tabName : sandboxName
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
      // Registry-only identity in the sandbox: no credential endpoint available to its code.
      identitySettings: [{identity: identity.id, lifecycle: mode == 'host' ? 'Main' : 'None'}]
    }
    template: {
      containers: [{
        name: mode
        image: image
        resources: {cpu: json('0.5'), memory: '1Gi'}
        env: [
          {name: 'TAB_MODE', value: mode}
          {name: 'TAB_TENANT_ID', value: tenant().tenantId}
          {name: 'TAB_APP_ID', value: appId}
          {name: 'TAB_ORIGIN', value: hostOrigin}
          {name: 'SANDBOX_ORIGIN', value: sandboxOrigin}
          {name: 'TAB_DIAGNOSTIC_CLIENTS', value: diagnosticClient}
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
      scale: {minReplicas: 0, maxReplicas: 1}
    }
  }
}]
output tabOrigin string = hostOrigin
output sandboxOrigin string = sandboxOrigin
