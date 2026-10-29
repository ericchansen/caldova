# Path4: actual Microsoft 365 Agents SDK proxy

Tested October 28, 2026. This is **not** Foundry's built-in publication, a
declarative plugin, a mock SDK, or an MCP Apps rendering solution.

## Documented contract and exact gap

Sources read during this investigation:

- [Microsoft 365 Agents SDK overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/m365-agents-sdk):
  custom orchestration and multiple channels, including Teams and M365 Copilot.
- [SDK quickstart](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/quickstart)
  (updated October 16): real `AgentApplication`, `CloudAdapter`,
  `start_agent_process`, and Activity replies. We use the authenticated variant,
  never the anonymous quickstart.
- [Authentication](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/configure-authentication-msal):
  Python MSAL user-assigned managed identity is supported for single-tenant hosting.
- [MCP Apps in Copilot](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps)
  (updated September 30): explicitly describes **declarative-agent MCP plugins**.
  It documents `_meta.ui.resourceUri`, tool-result delivery, resources/CSP,
  `app.callServerTool`, and host capabilities. These are not documented there as
  Activity attachment types or a custom-engine `send_activity` contract.
- [Teams SDK MCP server integration](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/in-depth-guides/ai-integrations/mcp-server)
  (updated October 9): `/api/messages` and `/mcp` are **two surfaces**. Exposing a
  bot as an MCP server does not document a Teams MCP Apps renderer. It also warns
  that older Teams AI/MCP plugins are deprecated in favor of external frameworks.

**No documented custom-engine Activity-to-MCP-Apps renderer contract was found.**
The missing part is a supported mapping from discovered UI tool metadata and
results to the native client renderer, including authenticated resource retrieval
and widget-originated tool callbacks. An SDK/backend that can call MCP tools is
not by itself that mapping. This implementation deliberately sends only text:
no proprietary attachment, HTML-as-card substitution, tab, or declarative plugin.
This is a bounded documentation finding, **not** a universal platform unsupported
claim. The direct M365 MCP Apps and reference-host positives remain valid.

## Implemented route

```text
Authenticated Teams personal / Direct Line Activity
  -> Agents SDK 1.9.0 JWT validation + CloudAdapter + AgentApplication
  -> user-assigned managed identity Entra token
  -> existing caldova-hosted-capabilities routed Responses endpoint
  -> final output_text
  -> authenticated Bot Connector Activity reply
```

No original bot/agent/auth configuration was changed. The starting hosted state
file identified v7. A live read **after** the smoke showed 100% routing to v8;
another worker owns the existing agent. We did not change that route. This proxy
is not version pinned, and the served version of each smoke turn is unknown.

## Pass/fail matrix

| Check | Result | Evidence/qualification |
|---|---|---|
| Real SDK installation and local tests | PASS | 1.9.0; original six cases, three source-configuration cases, two channel-diagnostic cases |
| Anonymous / malformed JWT ingress | PASS | Real deployed requests both HTTP 401 |
| ACR image | PASS after fix | `chg` failed on existing Unix user `proxy`; `chh` succeeded after renaming user |
| ARM scope/isolation | PASS | What-if creates only new proxy resources and two scoped assignments; original resources Ignore |
| Deployment/readiness | PASS | `caldova-proxy-path4`; ready revision `caldova-sdk-proxy--4a6bd1a` |
| Managed identity -> Foundry | PASS | HTTP 200, `mcp_list_tools`, one `mcp_call`, message |
| Authenticated SDK channel text reply | PASS, eventual | `proxy-b2d403da38eb`, actual counter 1 |
| Timely inbound acknowledgment | FAIL | Direct Line returned 502 / inner 504 "bot timed out"; eventual reply arrived |
| Personal custom-engine package | PASS, schema only | Teams 1.24 manifest instance has zero errors; no tenant publication |
| Teams personal UI installation / text + tool | PASS | UI-worker screenshot verified; source lookup and proxy `foundry_completed` correlate, one MCP call |
| M365 Copilot UI installation / text | INSTALLED / CHANNEL GATED | UI worker reached this proxy's explicit channel rejection; Foundry invocation not established for that turn |
| MCP Apps integration | UNIMPLEMENTED / NO DOCUMENTED CONTRACT FOUND | This proxy intentionally returns text; not a rendering FAIL |

Evidence: `evidence/proxy-runtime-result.json`; deployment/identity handoff:
`.azure/proxy-state.json`. Secrets were used only in memory for the new bot's
Direct Line smoke; none are in those files.

Actual Teams personal-bot control: run `proxy-teams-20261028-a`, source lookup
October 29 at 00:57:24.493Z, proxy completion at 00:57:29.204Z with
`mcp_call_count: 1`, and user-visible `orchards-verified` verified in the opened
screenshot. UI-worker evidence: `evidence/remaining-proxy-teams-pass-correlated.json`
and `evidence/proxy-teams-ui-result.json`. This establishes authenticated Teams
text/tool execution, **not MCP Apps integration or rendering**.

## Retained UI-worker handoff

- Package: `.azure/proxy-personal-app.zip`
- Display name: **Caldova SDK Proxy Lab**, version **1.0.0**
- Exact app/bot/tenant IDs, endpoint, image digest, package hash, resource scope,
  and role-assignment IDs are retained only in ignored `.azure/proxy-state.json`.
- Package has personal-only `bots` and `copilotAgents.customEngineAgents`, no
  declarative agent. Sideload only using the retained UI worker's existing permissions.
- UI worker subsequently installed the verified native M365 package and reached
  "This lab channel is not enabled." This supersedes the earlier `foreground0`
  installation blocker, but is not an Apps rendering result.
- Original logs correlate the response with the reported send time but did not
  record rejected channel IDs. Post-authentication `proxy_channel_received`
  diagnostics now capture exact channel ID, conversation type/group flag, and
  tenant presence/match booleans before the gate. No message/user/token payload is
  logged. A repeat UI turn is needed to verify the actual M365 shape before
  changing the allowlist; the SDK channel constant alone is not runtime evidence.
  The bounded attempt ended with diagnostics deployed on the same proxy and
  **no allowlist change**. No further UI action was requested: retain the initial
  M365 lab-gate result and the independently verified Teams text/tool PASS.

Use a fresh chat and distinct run IDs per client:

> Use show_table once with run_id proxy-teams-ui-20261028. Report its actual run
> ID and refresh counter. Do not call any email or send tool.

For Copilot substitute `proxy-m365-ui-20261028`. Allow up to three minutes for
an eventual reply because the synchronous ingress timeout is known. Capture
client errors, actual text, installation success, and any unexpected UI separately.
Do not mark Apps PASS without an actual rendered widget and real iframe Refresh.
Do not retry automatically: this minimal proxy has no distributed deduplication.

## Limits and retained resources

- Synchronous backend invocation can exceed Bot Service's ingress deadline.
  A production version needs authenticated durable enqueue/early acknowledgment
  and proactive reply, plus deduplication; **not implemented** in this bounded test.
- Single-turn backend calls; no durable conversation history or session pinning.
- Input limited to 8,000 characters; JSON experiment envelopes rejected.
  Output truncated at 24,000 characters. Attachments and invoke activities unsupported.
- Teams handler accepts only own-tenant personal conversations; other Teams
  scopes rejected. M365's actual activity shape remains a UI test, not assumed.
- New UAMI has AcrPull only on existing ACR and Cognitive Services User only on
  the existing Central US lab project. That role is broad **inside the project**;
  this is a synthetic lab, not a production least-privilege template.
- New bot's Direct Line is secret protected; SDK HTTP surface is JWT protected.
  No anonymous health/invocation route exists. Container probes use TCP.
- One replica remains running for the retained UI worker. No UI, email,
  licensing/trial, tenant-wide publication, security-policy, commit, or push action.

## Publication-safe source and final validation

Only these nine files belong in the source change:

```text
channels/proxy/.dockerignore
channels/proxy/Dockerfile
channels/proxy/README.md
channels/proxy/app.py
channels/proxy/main.bicep
channels/proxy/package.py
channels/proxy/requirements.txt
channels/proxy/smoke.py
channels/proxy/test_proxy.py
```

No generated tenant IDs, hostnames, app packages, bundles, local environments or
deployment outputs belong in that set. Built-in Azure role-definition IDs in Bicep
and synthetic UUIDs in tests are not generated tenant identities.

From the repository root, using the existing environments:

```powershell
.\.venv\Scripts\python.exe -m ruff check --no-cache channels/proxy
.\channels\proxy\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider channels/proxy/test_proxy.py
az bicep build --file channels/proxy/main.bicep --stdout | ConvertFrom-Json | Select-Object contentVersion
git --no-pager diff --check -- channels/proxy
git --no-pager diff --cached --check -- channels/proxy
git --no-pager diff --cached --name-only
git check-ignore .azure/proxy-state.json .azure/proxy-personal-app.zip evidence/proxy-runtime-result.json
```

For a fresh checkout, create `channels/proxy/.venv` and install `requirements.txt`,
`pytest`, `pytest-asyncio`, and `ruff==0.17.1` there; use that Python for both lint
and tests. Bicep `--stdout` avoids generating a compiled JSON bundle in source.

These validation commands do not deploy, send a new live prompt, regenerate the
retained ZIP, or change the running revision.

## Configuration and optional reproduction

The publication-safe source reads `PROXY_PROJECT_ENDPOINT` and `PROXY_AGENT_NAME`
in addition to `PROXY_CLIENT_ID` and `PROXY_TENANT_ID`. Bicep takes existing
environment/registry/account/project names as explicit parameters and supplies all
four runtime variables. Parameterization and channel diagnostics are now deployed
on the same owned proxy; exact ready revision/image are in ignored proxy state.
The allowlist and authentication guards remain unchanged. The retained ZIP is
unchanged; the verified Teams UI pass occurred on the original revision.

`smoke.py` reads keys **only** for `caldova-sdk-proxy` using the existing authorized
Azure CLI session and ignored proxy state, and never persists them. Run it only
when a new live synthetic invocation is wanted, not during lint/test validation.
`package.py` reads the ignored state's app/bot IDs and regenerates the ZIP
(ZIP timestamp changes its hash; use the retained package/hash for the UI handoff).
`main.bicep` is isolated infrastructure, not safe to apply outside this lab.

Coordinator cleanup after UI: delete only the new proxy bot, Container App, UAMI,
and its two role assignments, not the existing ACR/environment/project. Exact
identities are in ignored proxy state. **Keep the runtime available until then.**
