# Microsoft 365 and Teams channel tests

This directory contains the authenticated declarative-agent positive control. It connects directly to the same MCP fixture as the Foundry agent. The control is not a replacement for testing the published Foundry agent.

## Observed prerequisites

The lab Bot Service and Teams channel were deployed from [`infra/bot.bicep`](../infra/bot.bicep). Initial browser access was blocked. A later authorized session verified the correct lab account in both Copilot and the Teams Developer Portal. The Developer Portal UI allowed a home-tenant, single-app Entra SSO registration even though the earlier Azure CLI-token API read returned HTTP 403. That API result was not a tenant-wide access restriction.

The ordinary agent's version 7 publication API returned HTTP 200 with title and Teams app identifiers. Generated-package inspection confirmed the intended bot identity; endpoint readback confirmed 100% traffic pinned to version 7, Activity and Responses protocols, and Entra plus BotServiceRbac authorization. **Visibility is verified in both hosts:** the agent appeared in Copilot's Agents menu and opened in its own Teams personal chat. The Copilot route and Teams app ID matched the publication response. The earlier `publish_approval_status: not_published` readback and Graph catalog HTTP 403 did not prevent this UI discovery.

**MCP Apps conclusions remain unresolved.** Initial widget, tool-record, and greeting probes used a defective Bot Service messaging URL: it omitted the required `api-version` query. Copilot returned blank bubbles and later showed `timeout error after 45000ms`; Teams had no bot reply. The correlated log window contained no MCP POST, widget, lookup, or auth-rejection events. These initial results cannot establish a product rendering limitation.

The lab now supplies `api-version=2025-05-15-preview`, matching [azd's Activity messaging endpoint](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/internal/pkg/botservice/botservice.go). The bot was redeployed and the exact URL and identity read back. The corrected-route Copilot greeting reached a **User Sign-in** card instead of remaining blank. Selecting the already-signed-in lab account returned to the same agent conversation without credentials or MFA. An unchanged greeting retry then delivered an explicit Azure OpenAI `content_filter` error. No filter was changed. A normal fresh widget request was not sent because native composer focus could not be verified.

Direct API greeting controls still succeeded: version 7 with MCP configured took 35.69 seconds; version 1 without tools took 2.70 seconds. These are single-run diagnostics, not a benchmark or proof of the channel timeout's cause. A warm version-7 UI retry overlapped a diagnostic endpoint switch and is excluded from version-matched conclusions. A subsequent version-1 UI prompt was not sent because composer focus could not be verified. The endpoint is restored to version 7 after diagnostics.

The positive control has a real, home-tenant, single-app SSO registration. Its ZIP passed schema validation and Developer Portal import (`No issues found`). Teams rejected user sideloading with **`Uploading custom apps is not allowed`**. That policy remains unchanged.

The separately authorized [administrator-governed deployment](https://learn.microsoft.com/microsoft-365/admin/manage/agent-registry#upload-custom-agent) succeeded with both **Publish** and **Install** restricted to the exact test administrator and the default security template retained. The completion page confirmed both assignments. Microsoft [distinguishes this governed path from user sideloading](https://learn.microsoft.com/microsoftteams/teams-custom-app-policies-and-settings#how-the-distribution-method-affects-the-preview-setting).

The control appeared in Copilot's catalog and opened through its native catalog button. Its first opening displayed a load error; after one refresh it exposed the configured conversation starter. The `control-first` request received a text response saying the connector/tool was unavailable in the session, not a live widget. Deployment and chat availability are therefore verified, but successful MCP tool discovery/authentication and rendering are not. Managed-harness channel tests remain blocked by subscription preview enablement.

The diagnostic pinned package uses only `show_table`, with its schema and UI metadata taken from the authenticated MCP `tools/list` capture rather than re-created by hand. It preserves the control app ID, OAuth registration, and exact-user assignment. Generate this separately labeled package with:

```powershell
python -m caldova.publish control-package --pin-widget-from evidence\mcp-direct-discovery.json
```

This produces package version `1.0.1` with starter run ID `control-pinned`; the dynamic baseline uses version `1.0.0` and `control-first`. Preserve the baseline ZIP privately before replacing the local package. Update the existing governed app rather than creating a new identity or enabling user sideloading. The [documented pinned MCP configuration](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-dynamic-tool-discovery#plugin-manifest-differences) is a diagnostic comparison, not a successful rendering result by itself.

The bounded pinned diagnostic was executed after the admin center showed version `1.0.1`, retained single-user assignment, and Copilot exposed the new `control-pinned` starter. It also returned a text response saying the tool was unavailable in that session, without a widget or connector sign-in card. Application logs from 22:56 UTC through a verified 22:59:31 UTC watermark contained no matching MCP, tool, resource, auth-rejection, metadata, or run-ID event. A separate health probe established log freshness. This does not establish whether discovery, authentication, or ingress was attempted upstream, or where the integration failed. Do not infer MCP Apps non-support from either control result.

See the [sanitized channel observations](observations.json). Private screenshots and native UI snapshots are retained under ignored `evidence/m365-*`. Pre-correction host screenshots were opened to verify those visible results. The final pinned response is evidenced by a native accessibility snapshot; screenshot capture was refused because the lab window was not foreground. No screenshot, generated manifest, or tenant identifier is published here.

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

Reuse the existing verified lab-account browser session. Do not create repeated login windows. User sideloading remains prohibited; do not change that policy. The current control was deployed through the administrator-governed route with availability and installation scoped to one test user.

1. In the [Teams developer portal](https://dev.teams.microsoft.com/tools), create a **Microsoft Entra SSO client ID registration** for the lab MCP URL and existing lab Entra app. Restrict it to the home organization. Record the generated auth config ID and Application ID URI privately.
2. Follow [Microsoft's SSO configuration procedure](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso). The `control-sso` command adds the generated URI, consent redirect, and token-store preauthorization while retaining existing identifiers, roles, scopes, and clients. It verifies the additive settings by reading the app back. Check the issued token's audience against the fixture's validation; do not weaken issuer, audience, or permission checks.
3. Set the real registration ID and HTTPS fixture URL, then generate the package:

```powershell
$env:CALDOVA_AUTH_CONFIG_ID = '<actual-registration-id>'
$env:CALDOVA_SSO_APP_URI = '<portal-generated-application-id-uri>'
$env:CALDOVA_MCP_URL = '<deployed-https-mcp-url>'
python -m caldova.publish control-sso
python -m caldova.publish control-package
```

The resulting `.azure/control-app.zip` contains the manifests and generated PNG icons. Its stable app ID is stored in `.azure/m365-state.json`. Bind the SSO registration to that app ID before installation. The package requires `OAuthPluginVault`; there is no anonymous-auth fallback. Sideload only for the test user, following the [declarative-agent development procedure](https://learn.microsoft.com/microsoft-365/copilot/extensibility/build-mcp-plugins). Stop on policy or consent failures; do not change tenant-wide settings.

For an already deployed control, open its actual catalog entry rather than creating another app or synthesizing a launch ID. In environments where user sideloading is prohibited, an authorized administrator can use the documented **Agents > All agents > Add agent** route only after verifying that both availability and installation are restricted to the intended test user. Preserve the default security policy and review requested permissions before finishing.

For the ordinary agent, follow Microsoft's [published-agent runtime troubleshooting](https://learn.microsoft.com/azure/foundry/agents/how-to/troubleshoot-publish-copilot) before repeating widget probes. A fresh greeting must return through the channel first. No resource permission was broadened speculatively: the agent identity was enabled, and the tested MCP connection explicitly used project-managed identity.

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
