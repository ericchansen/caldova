targetScope = 'resourceGroup'

param botName string = 'caldova-prompt-bot'
param displayName string = 'Caldova Prompt Lab'
param agentClientId string
param tenantId string
param messagingEndpoint string

resource bot 'Microsoft.BotService/botServices@2022-09-15' = {
  name: botName
  location: 'global'
  kind: 'azurebot'
  sku: {
    name: 'F0'
  }
  properties: {
    displayName: displayName
    endpoint: messagingEndpoint
    msaAppId: agentClientId
    msaAppTenantId: tenantId
    msaAppType: 'SingleTenant'
    publicNetworkAccess: 'Disabled'
  }
}

resource teamsChannel 'Microsoft.BotService/botServices/channels@2021-03-01' = {
  parent: bot
  name: 'MsTeamsChannel'
  location: 'global'
  properties: {
    channelName: 'MsTeamsChannel'
  }
}

output botResourceId string = bot.id
