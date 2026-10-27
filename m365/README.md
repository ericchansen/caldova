# Microsoft 365 and Teams channel tests

This directory contains an authenticated **direct declarative-agent MCP plugin control**. It uses the same source fixture as the Foundry agent but is a different orchestration path.

## Current result

| Route | October 26 controlled result |
| --- | --- |
| Source MCP -> M365 declarative control | Rendered widget; real Refresh clicks advanced counters 1/2/3 during an authorized temporary Any Teams app authentication-binding comparison. |
| Source MCP -> Foundry prompt v7 -> M365 Copilot | Actual tool call, text only; no widget or Refresh. |
| Source MCP -> same Foundry prompt v7 -> Teams personal bot chat | Actual tool call, text only; no widget or Refresh. |

The latest text-only Copilot result supersedes earlier blank-response diagnostics. Both Foundry channel cases used **direct MCP, not Toolbox**. They retained the original version-7 publication, Responses/Activity and Entra/BotServiceRbac. These are two client surfaces of the same agent.

The direct control's original **SpecificApp/home-tenant restriction was restored and reloaded** after the successful comparison; developer mode was disabled. The pass is not a claim that the restored binding was separately proven to work. Authentication, scopes, one-user deployment audience and tenant security policies were not removed.

Microsoft documents [MCP Apps for declarative-agent MCP plugins](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps). That does not automatically establish support through a published Foundry agent. The separate [hosted SDK/reference-consumer proof](../hosted/README.md) has not been published to Teams or M365.

See [current evidence and route distinctions](../docs/results.md#mcp-apps-evidence) and the [sanitized channel record](observations.json). Earlier diagnostics are explicitly historical in that record; raw screenshots, identity/configuration readback and server logs remain private.

## Publish the ordinary Foundry agent

Run from the repository root with its Python environment activated, existing Azure CLI credentials and private `.azure/lab.json`:

```powershell
python -m caldova.publish bot
python -m caldova.publish publish --expected-version <verified-agent-version>
```

The bot helper previews scoped ARM changes. Publication refuses a mismatched latest version or bot identity, pins the specified immutable version, preserves protocols/authentication, downloads and checks the package, and uses `publishScope: Shared`. It does not create agent versions. Coordinate the publication pin with ongoing experiments.

State is written to `.azure/m365-state.json`; the package is `.azure/foundry-app.zip`. Do not repeat a successful publish merely to test UI availability: duplicate package versions are rejected. Inspect the existing app. Follow Microsoft's [publishing procedure](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).

The Bot Service messaging URL must include `?api-version=2025-05-15-preview`, as in [azd's publishing implementation](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/internal/pkg/botservice/botservice.go). Pre-correction failures are excluded from rendering conclusions.

### Prepare ordinary-agent prompt commands

```powershell
python -m caldova.publish ordinary-command-package
```

This offline helper derives `.azure/foundry-command-app.zip` from the generated package without overwriting it. It adds personal/Copilot `type: prompt` command entries and increments the package patch version, preserving identity, authentication, permissions, routing and other archive members. Existing command lists or missing scopes produce an error.

The package passed [manifest 1.29](https://developer.microsoft.com/json-schemas/teams/v1.29/MicrosoftTeams.schema.json) and preservation checks. Package generation alone neither installs it nor changes backend traffic. [Prompt starters](https://learn.microsoft.com/microsoftteams/platform/bots/how-to/conversations/prompt-starters) insert text; verify the actual composer and Send action rather than treating selection as submission.

## Prepare the authenticated direct control

Reuse the intended signed-in browser session. User sideloading was prohibited in this lab; the authorized [administrator-governed route](https://learn.microsoft.com/microsoft-365/admin/manage/agent-registry#upload-custom-agent) installed the control for exactly one user with the default policy. Do not relax tenant policy to install it.

1. Create a Microsoft Entra SSO registration in the [Teams developer portal](https://dev.teams.microsoft.com/tools) for the existing lab API. Retain the home-organization restriction and record its generated configuration ID and Application ID URI privately.
2. Follow the [SSO configuration procedure](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso). The helper adds the generated URI, consent redirect and token-store preauthorization while retaining existing roles/scopes/clients. It does not weaken the server's issuer, audience or permission checks.
3. Generate the package using real local values:

```powershell
$env:CALDOVA_AUTH_CONFIG_ID = '<actual-registration-id>'
$env:CALDOVA_SSO_APP_URI = '<portal-generated-application-id-uri>'
$env:CALDOVA_MCP_URL = '<deployed-https-mcp-url>'
python -m caldova.publish control-sso
python -m caldova.publish control-package
```

The package requires `OAuthPluginVault`; there is no anonymous fallback. Its stable app identity is kept in private state. Schema validation and portal import are prerequisites, not proof of working authentication or rendering.

The [OAuth/MCP guidance](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-oauth#use-the-teams-developer-portal) discusses specific-app binding limitations. In this lab the successful Any Teams app comparison was explicitly authorized, persisted/read back before the request, and rolled back afterward. It is not a standing instruction to broaden another registration.

For a separately labeled pinned diagnostic:

```powershell
python -m caldova.publish control-package --pin-widget-from evidence\mcp-direct-discovery.json
```

This uses the authenticated `show_table` descriptor, including UI metadata, rather than a hand-recreated schema. Preserve the baseline privately and update only the intended existing governed app. Do not infer success from changed package metadata.

## Rendering acceptance criteria

Open the actual agent's catalog entry; verify the server/agent identity and version. Submit a fresh run ID once. Require a live widget, an actual Refresh click and a changed result from the source server. Text, JSON, a model's rendering claim, an image, a link or HTTP 200 is not a rendering pass.

Keep the direct declarative plugin, direct Foundry prompt, Toolbox and hosted SDK routes distinct. Test Teams personal bot chat separately from Copilot embedded inside Teams. Preserve configuration and authentication throughout; record an inaccessible UI or unverified submission as blocked, not as product non-support.
