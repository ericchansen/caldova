param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$TenantId,
    [string]$Location = 'eastus2',
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:AZURE_SUBSCRIPTION_ID = $SubscriptionId
$env:AZURE_TENANT_ID = $TenantId
if ($Preview -and !(Test-Path .azure\lab.json)) {
    throw 'Initialize the lab identity with python -m caldova.cloud identity before previewing infrastructure.'
}
if (!$Preview) {
    & .\.venv\Scripts\python.exe -m caldova.cloud identity
    if ($LASTEXITCODE) { throw 'MCP identity setup failed' }
}
$state = Get-Content .azure\lab.json -Raw | ConvertFrom-Json
if (!$env:AZD_CONFIG_DIR) { $env:AZD_CONFIG_DIR = Join-Path (Get-Location) '.azure\azd-config' }
azd config set auth.useAzCliAuth true
if ($LASTEXITCODE) { throw 'azd configuration failed' }
if (!(Test-Path .azure\config.json)) {
    azd env new caldova --subscription $SubscriptionId --location $Location --no-prompt
    if ($LASTEXITCODE) { throw 'azd environment initialization failed' }
}
$values = @{
    AZURE_SUBSCRIPTION_ID = $SubscriptionId
    AZURE_TENANT_ID = $TenantId
    AZURE_LOCATION = $Location
    AZURE_PRINCIPAL_ID = $state.principal_id
    MCP_AUDIENCE = $state.mcp_app_id
}
foreach ($entry in $values.GetEnumerator()) {
    azd env set $entry.Key $entry.Value
    if ($LASTEXITCODE) { throw "Failed to set $($entry.Key)" }
}
if ($Preview) { azd provision --preview --no-prompt } else { azd provision --no-prompt }
if ($LASTEXITCODE) { throw 'Infrastructure deployment failed' }
if ($Preview) { return }
& .\.venv\Scripts\python.exe -m caldova.cloud outputs
if ($LASTEXITCODE) { throw 'Output collection failed' }
$state = Get-Content .azure\lab.json -Raw | ConvertFrom-Json
az acr build --subscription $SubscriptionId --registry $state.outputs.AZURE_CONTAINER_REGISTRY_NAME `
    --image caldova-mcp:lab --file Dockerfile .
if ($LASTEXITCODE) { throw 'MCP image build failed' }
$digest = az acr repository show --subscription $SubscriptionId `
    --name $state.outputs.AZURE_CONTAINER_REGISTRY_NAME --image caldova-mcp:lab --query digest -o tsv
if ($LASTEXITCODE -or !$digest) { throw 'Image digest lookup failed' }
$image = "$($state.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT)/caldova-mcp@$digest"
azd env set MCP_IMAGE $image
if ($LASTEXITCODE) { throw 'Image configuration failed' }
azd provision --no-prompt
if ($LASTEXITCODE) { throw 'MCP deployment failed' }
& .\.venv\Scripts\python.exe -m caldova.cloud outputs
if ($LASTEXITCODE) { throw 'Final output collection failed' }
