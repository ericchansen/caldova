# Microsoft 365 and Teams channel tests

This directory contains the authenticated declarative-agent positive control. It connects directly to the same MCP fixture as the Foundry agent. The control is not a replacement for testing the published Foundry agent.

## Observed prerequisites

The lab Bot Service and Teams channel were deployed from [`infra/bot.bicep`](../infra/bot.bicep). The dedicated Edge profile reached the Microsoft sign-in screen, not an authenticated Copilot conversation. A later passive check found that debug endpoint no longer reachable; it was not reopened. A read of the Teams Developer Portal using the existing Azure CLI credential returned HTTP 403 with an empty body. This does not establish a tenant policy restriction or lack of MCP Apps support.

The ordinary agent's version 7 publication API returned HTTP 200 with title and Teams app identifiers. Generated-package inspection confirmed the intended bot identity; endpoint readback confirmed 100% traffic pinned to version 7, Activity and Responses protocols, and Entra plus BotServiceRbac authorization. Store visibility is **not verified**: the endpoint still reported `publish_approval_status: not_published`, and reading the exact Teams catalog record with the existing Graph credential returned HTTP 403. The publication response alone does not resolve those observations.

**UI tests are BLOCKED pending authenticated host access and control registration.** No live widget, refresh counter, or Foundry channel-parity result has been observed. The managed-harness channel tests also depend on the separate subscription preview-access blocker. Do not retry interactive authentication without the user's approval.

The templates passed instance validation against the linked Microsoft JSON schemas. This is not proof of successful registration, installation, authentication, or rendering.

Backend UI-resource probes distinguish the routes: direct MCP `resources/read` returned `ui://caldova/table`, while the catalog Toolbox preserved the tool's `_meta.ui.resourceUri` but returned `No resource provider handles URI 'ui://caldova/table'` for the same resource read. Private evidence is in `evidence/mcp-direct-auth-control.json` and `evidence/toolbox-ui-resource.json`. This is an observed Toolbox resource-forwarding failure, not a conclusion about direct-MCP rendering in Microsoft 365. The published version 7 deliberately uses direct MCP.

## Publish the ordinary Foundry agent

Run commands from the repository root with its Python environment activated. Existing Azure CLI credentials and ignored `.azure/lab.json` must be available. The helper uses the lab subscription explicitly for ARM operations.

```powershell
python -m caldova.publish bot
python -m caldova.publish publish --expected-version <verified-widget-agent-version>
```

The bot command runs a scoped ARM what-if before deployment. The publish command refuses a mismatched latest version or bot identity, pins endpoint traffic to the specified immutable version, downloads the generated package, checks its bot ID, and publishes with `publishScope: Shared` only. It verifies that pinning preserves the existing protocols and authorization. It does not create agent versions. Coordinate with the backend test runner before selecting the version for channel tests.

Generated state is saved in `.azure/m365-state.json`; the Foundry package is `.azure/foundry-app.zip`. Private responses and manifest readback are saved under `evidence/m365-*`. A successful publication API response is only a provisioning result, not an MCP Apps pass. See Microsoft's [REST publishing procedure](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).

The lab publication uses app package version `1.0.0`. Do not rerun a successful publish to test availability: the service rejects duplicate package versions. Inspect the existing app instead. A deliberate metadata update requires an incremented package version; changing backend traffic uses the agent endpoint selector.

## Complete the positive control

After the user permits reopening the browser and completes sign-in, reuse the existing dedicated Edge profile. Do not create repeated login windows.

1. In the [Teams developer portal](https://dev.teams.microsoft.com/tools), create a **Microsoft Entra SSO client ID registration** for the lab MCP URL and existing lab Entra app. Restrict it to the home organization. Record the generated auth config ID and Application ID URI privately.
2. Follow [Microsoft's SSO configuration procedure](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso). Add the generated URI without removing the existing identifier URI. Add the consent redirect URI and preauthorize the Microsoft Enterprise token store for the existing `Mcp.Access` scope. Preserve the existing Azure CLI preauthorization, application role, and scope. Check the issued token's audience against the fixture's validation; do not weaken issuer, audience, or permission checks.
3. Set the real registration ID and HTTPS fixture URL, then generate the package:

```powershell
$env:CALDOVA_AUTH_CONFIG_ID = '<actual-registration-id>'
$env:CALDOVA_MCP_URL = '<deployed-https-mcp-url>'
python -m caldova.publish control-package
```

The resulting `.azure/control-app.zip` contains the manifests and generated PNG icons. Its stable app ID is stored in `.azure/m365-state.json`. Bind the SSO registration to that app ID before installation. The package requires `OAuthPluginVault`; there is no anonymous-auth fallback. Sideload only for the test user, following the [declarative-agent development procedure](https://learn.microsoft.com/microsoft-365/copilot/extensibility/build-mcp-plugins). Stop on policy or consent failures; do not change tenant-wide settings.

## UI acceptance criteria

First open **Caldova MCP Control** in [Microsoft 365 Copilot](https://m365.cloud.microsoft/chat). Ask for the live fixture table with a fresh run ID. Capture the rendered widget and its initial counter, click **Refresh**, and capture the changed server counter with the same run ID. Correlate this with the server's tool-call trace and resource fetch.

Only then repeat with **Caldova Prompt Lab**, first in Copilot web and then in the agent's personal chat in [Teams web](https://teams.microsoft.com). The Copilot app embedded inside Teams is a different surface. Confirm the active backend agent version, route, and run ID for each case. Repeat one discovery, skill-loading, and large-result probe through each channel without inferring backend behavior from final text alone.

An MCP Apps pass requires a visible live widget and its refresh-to-server round trip. Text, JSON, an image, a card, an external link, or a successful HTTP response is not a pass. Keep direct MCP, Toolbox, and Tool Search routes separate. A blocked positive control leaves dependent UI conclusions blocked, not unsupported. See [MCP Apps support and requirements](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps).

Keep screenshots and raw responses private. Persist each case immediately with its surface, run ID, agent/model/toolbox versions, expected observation, actual observation, and evidence paths. Do not publish tenant IDs, account details, or generated manifests.

## Checks and cleanup

```powershell
python -m unittest discover -s m365 -v
ruff check caldova\publish.py m365
```

Keep the lab available for review. When explicitly requested, uninstall only the two lab apps, remove only their SSO registration, and delete only `caldova-prompt-bot` from the lab resource group. Do not delete or modify unrelated apps, bot resources, or tenant policies.
