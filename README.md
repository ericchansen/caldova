# Caldova

A reproducible Foundry Prompt Agent lab for four questions:

1. Does Toolbox discover tools on demand?
2. Does it discover and selectively load skills?
3. Do MCP Apps render when the same Foundry agent is published to Microsoft 365 Copilot and Teams?
4. Does the harness automatically offload large MCP responses to files?

**[Read the current results](docs/results.md) and [hosted implementation](hosted/README.md).** A Foundry-hosted GitHub Copilot SDK agent rendered an MCP App in a reference browser through its experimental native MCP Apps APIs; a real Refresh advanced the counter. The hosted SDK also automatically offloaded 32/256-KiB remote MCP results to verified files. This is not the gated Foundry-managed Copilot prompt harness, whose behavior remains unmeasured.

The ordinary Foundry prompt agent returned text only in the playground, M365 Copilot and Teams. Toolbox tool calls worked, but its advertised UI resource could not be read. A direct M365 declarative-plugin control rendered successfully during a bounded authentication-binding comparison. These are distinct paths, not interchangeable support guarantees.

The hosted agent was subsequently published as a separate personal-scope app. Actual M365 Copilot and Teams personal-chat requests both invoked the MCP tool but displayed text only, not a widget. The reference-browser success is therefore not a demonstrated published-channel solution. [Channel evidence and version-attribution limit](docs/results.md#hosted-publication-to-m365-and-teams).

**Additional integration passes:** a declarative MCP plugin backed by an authenticated facade and the Foundry-hosted SDK rendered/refreshed the real App in both M365 Copilot web and Copilot inside Teams. A separate authenticated Teams personal tab also rendered/refreshed through Foundry. These are different integrations from Foundry's built-in publication: the first uses Copilot as the outer orchestrator and Foundry for delegated model execution; the second embeds an application-owned renderer in Teams. [Pathway matrix and test conditions](docs/results.md#additional-m365-and-teams-pathways).

## Architecture

`infra/main.bicep` provisions only `rg-caldova-demo`: a new Foundry account/project, a shared `gpt-5-mini` model deployment, an authenticated synthetic MCP server on Container Apps, a private image registry, and logs. The lab uses Entra tokens, not embedded API keys.

`caldova-prompt` omits the harness property. New `caldova-copilot` creation requests use the canonical `microsoft_copilot_preview` discriminator with `Foundry-Features: MicrosoftCopilot=V1Preview`. Historical evidence also includes the legacy `github_copilot_preview` pair. Both were explicitly refused in the tested Central US project; the experiment records refusal rather than substituting another runtime.

The original account is in East US 2. A later public harness-region policy excluded that region, so the lab added a separate Central US Foundry account/project/model inside the same resource group. Its managed-harness creation was also refused. The existing MCP server and published East US 2 agent were not moved or repinned. [Regional controls](docs/results.md#supported-region-control) distinguish the region correction from the remaining subscription gate.

Foundry tools use project-managed identity. Direct developer probes use delegated `Mcp.Access`; application callers require the lab's `Mcp.Invoke` app role. The health endpoint contains only fixture readiness information. Model deployment capacity is an allocation within existing quota, not provisioned throughput.

The public repository contains no tenant configuration or raw service evidence. `.azure/` contains deployment state; `evidence/` contains append-preserved test results. Keep both private.

## Prerequisites

- Python 3.11+, Azure CLI, Azure Developer CLI (`azd`), and Bicep.
- An existing authenticated Azure CLI session for the intended tenant.
- Permissions to create the lab resources, scoped role assignments, and its Entra application.
- Available Global Standard model quota and a supported region. Defaults are East US 2 and `gpt-5-mini` version `2025-08-07`.
- Separate preview enablement for the managed harness. Its public authoring schema does not guarantee subscription access.
- For UI tests: a licensed Microsoft 365 user, permission to install test apps, and an authenticated browser session in that tenant.

Do not keep launching login flows. Use the existing CLI session; if a browser requires a human sign-in, stop that UI path and continue independent API tests.

## Local checks

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\ruff.exe check caldova tests m365 hosted
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m unittest discover -s m365 -p "test_*.py" -v
az bicep build --file infra\main.bicep
az bicep build --file infra\bot.bicep
```

The tests cover payload boundaries/hidden markers, MCP App metadata, and JWT audience/issuer/expiry/permission rejection. They do not assert undocumented service behavior.

## Provision

Set these values locally, not in committed files:

```powershell
$env:AZURE_SUBSCRIPTION_ID = "<subscription-id>"
$env:AZURE_TENANT_ID = "<tenant-id>"
$env:AZD_CONFIG_DIR = Join-Path (Get-Location) ".azure\azd-config"

# Creates the lab-specific Entra application and ignored local state.
.\.venv\Scripts\python.exe -m caldova.cloud identity

# Initialize the isolated azd environment.
azd config set auth.useAzCliAuth true
azd env new caldova --subscription $env:AZURE_SUBSCRIPTION_ID --location eastus2 --no-prompt

# Preview ARM changes before provisioning.
.\scripts\provision.ps1 -SubscriptionId $env:AZURE_SUBSCRIPTION_ID -TenantId $env:AZURE_TENANT_ID -Preview
.\scripts\provision.ps1 -SubscriptionId $env:AZURE_SUBSCRIPTION_ID -TenantId $env:AZURE_TENANT_ID
```

The script uses Bicep through azd, builds the fixture image with ACR Tasks, and deploys it with managed-identity image pull. It never enables anonymous registry access. ARM persists provisioning progress if the CLI is interrupted.

Create the secretless project connection after provisioning:

```powershell
$state = Get-Content .azure\lab.json -Raw | ConvertFrom-Json
azd extension install azure.ai.agents --no-prompt
azd env set AZURE_AI_PROJECT_ID "/subscriptions/$($state.subscription)/resourceGroups/rg-caldova-demo/providers/Microsoft.CognitiveServices/accounts/$($state.outputs.FOUNDRY_ACCOUNT_NAME)/projects/capability-lab"
.\.venv\Scripts\python.exe -m caldova.cloud authorize
azd ai connection create caldova-mcp --kind remote-tool `
  --target $state.outputs.MCP_ENDPOINT --auth-type project-managed-identity `
  --audience "api://$($state.mcp_app_id)" `
  --project-endpoint $state.outputs.FOUNDRY_PROJECT_ENDPOINT --no-prompt
```

Connections, agent versions, skill versions, and Toolbox versions are data-plane objects. The experiment scripts manage these; Bicep manages ARM infrastructure. `caldova.cloud authorize` grants only access to the synthetic MCP application.

## Run the experiments

```powershell
# Records both outcomes. May exit nonzero if the managed harness is gated.
.\.venv\Scripts\python.exe -m caldova.experiments create-agents

# These can continue against the successfully created ordinary agent.
.\.venv\Scripts\python.exe -m caldova.experiments connect-tools
.\.venv\Scripts\python.exe -m caldova.experiments skills
.\.venv\Scripts\python.exe -m caldova.inspect_mcp caldova-catalog
.\.venv\Scripts\python.exe -m caldova.inspect_mcp caldova-search
.\.venv\Scripts\python.exe -m caldova.inspect_mcp caldova-skills
.\.venv\Scripts\python.exe -m caldova.inspect_mcp direct --read-ui
# This probe currently fails on the tested Toolbox resource-forwarding path.
.\.venv\Scripts\python.exe -m caldova.inspect_mcp caldova-catalog --read-ui

.\.venv\Scripts\python.exe -m caldova.experiments discovery --toolbox caldova-search
.\.venv\Scripts\python.exe -m caldova.experiments discovery --toolbox caldova-catalog
.\.venv\Scripts\python.exe -m caldova.experiments discovery --toolbox caldova-skills
.\.venv\Scripts\python.exe -m caldova.experiments native-skills

# Restore direct MCP attachment before measuring raw result handling.
.\.venv\Scripts\python.exe -m caldova.experiments connect-tools
.\.venv\Scripts\python.exe -m caldova.experiments spill
# Rerun only selected sizes, if needed:
.\.venv\Scripts\python.exe -m caldova.experiments spill --sizes 1024 32768
```

Requests are recorded before transport, including the explicit `Foundry-Features` value but not authorization headers; responses are saved before interpretation. Repeated runs get distinct evidence files. Model calls incur usage charges. The payload ladder ends at 1 MiB and stops escalation after a service error. Extraction requires exactly the BEGIN and MIDDLE values; the follow-up requests the withheld END value and rejects a fresh `large_result` call as proof of retention.

Discovery creates explicit agent versions but does not change a published endpoint's pinned version. Keep the publication pin on the verified direct-MCP version unless deliberately testing a different route. [M365 setup](m365/README.md) covers the publishing helper and authenticated positive control. [Hosted experiments](hosted/README.md) contain the separate SDK runtime, generic caller adapter and offload measurements.

## Interpret evidence correctly

### Supported-region control

Do not change the existing deployment's location to test a different region. The optional Foundry-only control reuses `infra/foundry.bicep` and leaves the existing server, bot, and publication untouched:

```powershell
# Read current public harness regions, exact model offer, quota, and incremental what-if.
.\.venv\Scripts\python.exe -m caldova.region --location centralus

# Apply only after reviewing the scoped changes.
.\.venv\Scripts\python.exe -m caldova.region --location centralus --deploy

# Explicit secondary state prevents either project's versions from replacing the other's.
.\.venv\Scripts\python.exe -m caldova.experiments create-agents --state .azure\harness-region.json
.\.venv\Scripts\python.exe -m caldova.experiments skills --state .azure\harness-region.json
.\.venv\Scripts\python.exe -m caldova.experiments native-skills --state .azure\harness-region.json
.\.venv\Scripts\python.exe -m caldova.inspect_mcp caldova-skills --state .azure\harness-region.json
```

The provisioner rejects deletes and changes outside the new account's resource namespace. It uses existing quota, verifies deployment outputs/model readback, and writes only `.azure/harness-region.json`; repeated deployments preserve that project's experiment state. Model/account resources remain billable, and the extra allocation consumes quota. The regional project is not automatically published to M365 or authorized to invoke the shared MCP fixture. Its successful skill-resource reads do not require changing the fixture's authentication.

Both experiment CLI and protocol probe support `--state`; default calls still use `.azure/lab.json`. Request/response evidence includes the project endpoint so identically named agents in different projects are not confused.

### Evidence boundaries

- `tools/list` changing from the full catalog to search meta-tools proves a smaller initial protocol surface. It does not guarantee lower total token usage.
- Skill metadata and body/resource reads prove delivery. Only agent traces or observable loading can establish automatic progressive use by that agent.
- A missing required skill answer is a failed functional case, even when the failure cause or loading mechanism remains indeterminate. Header toggles and definition readback do not reveal hidden runtime operations.
- Filesystem capabilities are not proof of automatic spill-to-disk. The primary test does not ask for file writes, use Code Interpreter, or pre-save data on the MCP server.
- A completed answer is not proof of offload. Inspect raw result size, usage, file references, selective reads, and failure boundaries.
- Our local evidence files are created by the test runner, not the Foundry harness.
- MCP Apps require a rendered widget and a real refresh round-trip in the target host. Preserved metadata or successful publication alone is insufficient.
- Subscription gating, browser sign-in, and registration permissions are BLOCKED cases, not evidence of product non-support.

## Review and cleanup

Retain the lab for review. Container Apps is configured for zero minimum replicas, although platform health/traffic behavior can keep it active. The registry, logs, inference, and other provisioned services can still incur charges.

Cleanup is intentionally not automatic. Inventory `rg-caldova-demo`, the lab-specific Entra app/service principal, Foundry agent/Toolbox/skill records, and any generated Microsoft 365 app registrations. Remove only lab-owned objects after approval; never run cleanup against an existing shared resource group. Export wanted evidence before removing anything.

## Sources

- [Foundry Bicep deployment](https://learn.microsoft.com/azure/foundry/how-to/create-resource-template)
- [Managed harness creation](https://github.com/microsoft/azure-skills/blob/main/skills/microsoft-foundry/foundry-agent/create/create-managed-harness.md)
- [Tool Search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search)
- [Skills through Toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/skills#attach-skills-to-a-toolbox-preview)
- [Microsoft 365 MCP Apps](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps)
- [Entra SSO plugin authentication](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso)
