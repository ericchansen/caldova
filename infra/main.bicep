targetScope = 'subscription'

param environmentName string = 'caldova'
param location string = 'eastus2'
param resourceGroupName string = 'rg-caldova-demo'
param principalId string
param modelName string = 'gpt-5-mini'
param modelVersion string = '2025-08-07'
param modelCapacity int = 400
param mcpAudience string
param mcpImage string = ''

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    'azd-env-name': environmentName
    purpose: 'synthetic-agent-capability-tests'
  }
}

module lab 'lab.bicep' = {
  name: 'caldova-lab'
  scope: rg
  params: {
    location: location
    principalId: principalId
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    mcpAudience: mcpAudience
    mcpImage: mcpImage
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_PROJECT_ENDPOINT string = lab.outputs.projectEndpoint
output FOUNDRY_ACCOUNT_NAME string = lab.outputs.accountName
output FOUNDRY_MODEL string = modelName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = lab.outputs.registryEndpoint
output AZURE_CONTAINER_REGISTRY_NAME string = lab.outputs.registryName
output MCP_ENDPOINT string = lab.outputs.mcpEndpoint
output MCP_AUDIENCE string = mcpAudience
output MCP_HOST_NAME string = lab.outputs.hostName
