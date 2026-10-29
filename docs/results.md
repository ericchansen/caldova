# Foundry capability test results

**Current checkpoint: October 28, 2026 (Pacific; some evidence timestamps are October 29 UTC).** These are synthetic lab observations, not a general availability or support guarantee. The [sanitized record](observations.json) separates current outcomes from historical diagnostics. Raw service responses and UI evidence remain private.

**Bottom line:** a Foundry-hosted GitHub Copilot SDK agent can support an MCP Apps consumer through the SDK's experimental native APIs and a generic transport adapter. The ordinary Foundry prompt-agent route did not render Apps. Toolbox forwarded tool calls but failed to retrieve their advertised HTML resource. Automatic large-result offload was verified in the hosted SDK, not in the subscription-gated Foundry-managed Copilot harness.

**The remaining-path investigation also produced actual native M365 web and Copilot-inside-Teams passes through a Foundry-backed declarative MCP plugin, plus an embedded Teams-tab pass.** All used the Foundry-hosted model runtime and real widget Refresh callbacks. They do not change the earlier text-only outcome for Foundry's built-in published-agent channel.

## Additional M365 and Teams pathways

| Integration | Foundry's role | Current observed result |
| --- | --- | --- |
| Direct declarative MCP plugin in M365 | None in the original control | PASS under the recorded bounded auth comparison |
| Original direct declarative plugin inside Teams Copilot | None | Tool-error response under unchanged SpecificApp/HomeTenant; no rendering verdict |
| Declarative MCP plugin -> remote facade -> hosted SDK | Delegated model execution plus native MCP tool/resource operations | PASS in M365 web AND Copilot inside Teams: visible App and actual Refresh, counter 1 to 2 in each |
| Foundry built-in publication, ordinary prompt | Agent runtime | Text only in playground, M365 and Teams |
| Foundry built-in publication, hosted SDK | Agent runtime | Text only in M365 and Teams; existing Teams session version attribution qualified |
| Custom Microsoft 365 Agents SDK proxy -> Foundry | Agent runtime behind an application-owned channel proxy | Native Teams text/tool control passed. Native M365 reached the lab's channel allowlist gate. MCP Apps renderer integration is not implemented, not a tested rendering failure |
| Copilot Studio -> authenticated Foundry-backed MCP connector | Delegated agent behind Studio orchestration | Connector created; actual delegated sign-in failed. Runtime/rendering blocked, not an MCP Apps failure |
| Teams personal tab -> application-owned AppBridge -> hosted SDK | Delegated model execution and native MCP operations | PASS inside Teams: visible App and actual inner Refresh, counter 1 to 2 |

### Native M365 through a Foundry-backed MCP plugin

```text
M365 declarative agent + native MCP Apps renderer
  -> enterprise-hosted, Entra-authenticated MCP facade
    -> Foundry hosted Responses endpoint
      -> Copilot SDK model turn
        -> source MCP tool
```

The model actually executes the delegated tool; this is not a facade returning synthetic answers without Foundry. Tool discovery and HTML reads use the hosted SDK's native MCP APIs. The facade never fetches HTML directly from the source server. [Implementation and boundaries](../channels/README.md).

Initial SpecificApp tests returned token-store-error prose, without a raw diagnostic sufficient to prove an app-ID mismatch. Under a bounded AnyApp comparison the request reached the facade, but live logs showed discovery took 45-53 seconds and exceeded the client deadline. After startup catalog preloading and a warm facade replica, a control measured discovery at 0.188 seconds, and the actual corrected M365 case passed.

Run `facade-m365-cached-20261028-a` displayed counter 1. A real widget Refresh was clicked at `2026-10-29T00:29:08.087Z`; visible counter 2 was verified at `00:29:26.915Z`. Source calls at `00:28:10.2837294Z` and `00:29:20.2621523Z` match both results. The source HTML read and both completed facade calls are also recorded. Screenshots were captured and opened.

**Conditions:** corrected cached-discovery implementation, a warm facade, temporary Any Teams app registration applicability, home-tenant restriction, and exact single-user Publish/Install assignment. Full SpecificApp baseline restoration was verified at `00:31:31.055Z`; developer mode was off. This is not a pass under the restored SpecificApp setting and not a pure causal authentication A/B comparison.

The same integration subsequently passed in **Copilot inside TeamsModern/web**, not personal bot chat. Run `facade-teams-20261028-a` rendered counter 1, an actual inner Refresh was clicked at `00:39:19.660Z`, and counter 2 was visibly verified. Source calls at `00:38:28.9110712Z` and `00:39:33.8833707Z` match the results. The temporary new-registration AnyApp/HomeTenant condition was restored to the full SpecificApp baseline at `00:40:19.841Z`. Screenshots were captured and opened. Malformed citation text appeared beneath the otherwise working widget; this was not a polished production UX.

Copilot remains the outer orchestrator; Foundry executes delegated model turns. Downstream authorization uses application identity, not end-user OBO. Only synthetic data was tested.

### Real Teams embedded web client

The [Teams tab](../channels/tab/README.md) uses Teams SSO, a dedicated authenticated backend and an official AppBridge with a separate-origin sandbox. It invokes Foundry's `delegated_rpc` operation, including for actual widget callbacks. This is an application tab in Teams, not native Teams bot chat or Copilot chat.

The first UI attempt exposed a lab timeout: the sandbox's first byte arrived at 38.879 seconds after the original 30-second readiness listener expired. The corrected bounded wait is 120 seconds and still checks the official message, exact iframe source and origin; no authentication or CSP restriction was relaxed.

The corrected run `tab-172810d6a64b421788f5a564b8ec8fe7` rendered counter 1 inside TeamsModern/web. The actual inner Refresh was clicked at `00:22:05.589Z`, with visible counter 2 verified by `00:22:22.050Z`. Source calls at `00:21:43.2657617Z` and `00:22:18.3507335Z` correlate with the authenticated tab backend's two Foundry response IDs. Both screenshots were captured and opened.

### Remaining boundaries

The proxy's intentional text-only implementation must not be called an MCP Apps rendering failure. Native Teams personal-bot run `proxy-teams-20261028-a` returned `orchards-verified`; the source lookup at `00:57:24.4939966Z` and proxy completion at `00:57:29.2045995Z` confirm one real Foundry-backed MCP call. Its native M365 request returned the lab's own "This lab channel is not enabled" message. The original logs did not identify the incoming channel, so the allowlist was not broadened speculatively; a later diagnostic-only deployment is not a fix or a passing M365 test. The earlier Direct Line control also observed an acknowledgment timeout before the eventual text reply. No documented native custom-engine MCP Apps attachment/resource/callback contract was established.

Studio's actual delegated connection reported "Unable to sign in. Please try again." The client, callback, scope, endpoints and unexpired service-side credential were checked without identifying a configuration defect; no Studio tool/runtime/rendering pass is claimed. The original direct-control agent was also exercised inside Teams Copilot under its unchanged SpecificApp/HomeTenant settings and returned tool-error prose, not a widget; it was not granted the temporary applicability used for the separate facade pass.

## All four questions

| Question | Observed answer | Boundary |
| --- | --- | --- |
| Progressive tool discovery | PASS: Toolbox replaced 26 definitions with `tool_search` and `call_tool`; three tasks found and called the correct tools. | Deferred definitions, not a demonstrated total-token saving in this small catalog. |
| Progressive skills | Metadata and body/archive delivery PASS; tested ordinary-agent automatic skill-use cases FAIL; explicit downloaded-body preload PASS. | Toolbox supplies the resources. The consuming harness must discover and apply them. Managed-harness skill consumption was not tested. |
| MCP Apps through a Foundry agent | Ordinary prompt route: text only. Hosted Copilot SDK direct-MCP route with an Apps renderer: PASS. Toolbox resource route: FAIL. | A renderer, transport and runtime must all preserve the Apps contract. The original custom hosted prototype bypassed Toolbox for HTML. |
| Default large-result file offload | Hosted Copilot SDK: observed at 32/256 KiB; 1 KiB inline. Ordinary prompt agent: no automatic file observed; 1 MiB exceeded context. | Managed Copilot prompt harness: BLOCKED by subscription enablement. Offload does not prevent subsequent full-file reads into context. |

Toolbox is the discovery/access layer, not a browser renderer or a universal agent harness. [Tool Search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) and [skills through Toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/skills#attach-skills-to-a-toolbox-preview) describe the relevant product contracts.

## MCP Apps evidence

PASS below requires an actual widget and an actual Refresh-to-server round trip, not a model claiming it displayed an app.

| Path | Result | What was actually exercised |
| --- | --- | --- |
| Source MCP -> official reference host | PASS | Widget, rows and Refresh; counter advanced from 1 through 8. |
| Source MCP -> M365 declarative-agent plugin | PASS, bounded auth comparison | Widget and two Refresh clicks; counters 1/2/3. Temporary Any Teams app applicability, home tenant/auth retained; original SpecificApp restriction restored. |
| Source MCP -> ordinary Foundry prompt v7 -> playground | FAIL to render | `show_table` executed; visible prose/bullets, no widget. |
| Source MCP -> same published prompt v7 -> M365 Copilot | FAIL to render | Fresh controlled request returned text only; tool call confirmed. This supersedes older blank replies. |
| Source MCP -> same published prompt v7 -> Teams personal bot chat | FAIL to render | Fresh controlled request returned text only; tool call confirmed. This was not Copilot embedded inside Teams. |
| Source MCP -> Toolbox -> prompt v9, API inspection | Tool PASS; resource FAIL | UI URI retained by Toolbox, but `resources/read` rejected it. Foundry Responses descriptors omitted UI metadata and returned a stringified tool result. |
| Source MCP -> Toolbox -> hosted custom handler -> reference host | PASS only with bypass | One hard-coded tool; HTML fetched directly from source MCP, not Toolbox. Real warm Refresh returned counter 2. |
| Source MCP -> hosted native Copilot SDK -> generic adapter -> reference host | PASS | Real UI showed counter 1; actual iframe Refresh produced counter 2. Native SDK catalog had 26 tools; separate model probe selected both UI and ordinary tools. |
| Source MCP -> Toolbox -> hosted native SDK -> reference host | Resource/render FAIL | Tool returned counter 1; no widget. The correlated hosted runtime log recorded the same resource-provider error, with no source fallback. |
| Hosted SDK agent -> published M365 Copilot | No rendering pass | Fresh conversation after publication/pin correction; real tool call, text only, no widget/Refresh. |
| Hosted SDK agent -> published Teams personal bot | No rendering pass; served-version qualification | Real tool call, text only, no widget/Refresh. Existing personal conversation; its actual served version was not exposed in available traces. |
| Customer's actual MCP server and application | NOT TESTED | All runtime experiments used the authenticated synthetic fixture. |

### Same agent, different client contract

The M365 and Teams tests used the **same Foundry agent and version**. Publishing it does not replace its runtime with a declarative agent or automatically preserve MCP Apps metadata. Microsoft's [M365 MCP Apps documentation](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps) covers declarative-agent MCP plugins; that working direct control is a separate orchestration route.

The latest ordinary-agent requests were `foundry-reference-20261026-a` in the playground, `foundry-published-copilot-20261026-b` in M365 and `foundry-published-teams-20261026-b` in Teams. All used direct MCP, **not Toolbox**. Published readback retained version 7 at 100%, Responses/Activity and Entra/BotServiceRbac. Neither published request fetched the widget resource in its scoped source-server logs.

### Where Toolbox blocks

An authenticated direct source read of `ui://caldova/table` succeeds. The Toolbox retains `_meta.ui.resourceUri` but returns:

```text
No resource provider handles URI 'ui://caldova/table'.
```

Declaring the MCP Apps client capability did not change that result. This is a failed resource-forwarding path before a consumer can obtain HTML through Toolbox, not a failure of ordinary tool execution. It is not proof that fixing this one issue would resolve all metadata, tool-name and client-rendering boundaries.

### What the hosted implementation changes

The runtime is **GitHub Copilot SDK 1.0.11 / CLI 1.0.79**, hosted with `azure-ai-agentserver-responses==2.3.0`, not Microsoft Agent Framework. The generic path enables experimental MCP Apps, configures the MCP server once, and delegates to `session.rpc.mcp.apps.list_tools`, `read_resource` and `call_tool`. It does not implement one Python wrapper per tool.

The [complete caller chain and code](../hosted/README.md) distinguish this from the earlier single-tool resource bypass. The browser remains the renderer. Its MCP requests pass through a small MCP-to-Responses adapter to the hosted SDK APIs. Model selection was tested separately through a real SDK model turn; explicit widget callbacks need no extra model turn on the native path.

The native direct UI proof used `native-ui-direct-20261027-a`: counter 1, then an actual Refresh click at 01:50:03 UTC and visible counter 2 by 01:50:19 UTC. The same browser catalog's `lookup_orchards` call returned `orchards-verified`. Native accessibility snapshots captured the nested MCP App and table. Foreground-only screenshot capture was unavailable; no screenshot is claimed for this case.

The pure native Toolbox comparison used `native-ui-toolbox-20261027-a`. The browser received a successful tool result but no widget or visible error explanation. The hosted log at 01:47:21 UTC independently identified `session.mcp.apps.readResource` failing with `No resource provider handles URI 'ui://caldova/table'`; its corresponding Responses request returned HTTP 500. No fallback or repeat call was used.

One configured source server and one live UI bundle were exercised. Dynamic tool/URI routing has unit coverage, but multiple live servers, production permissions, arbitrary UI packages and catalog-scale performance remain unvalidated.

### Hosted publication to M365 and Teams

The isolated **Caldova Hosted Lab** was published through Foundry's Microsoft 365 API using `Shared` (Just you) scope, a separate Bot Service resource and the hosted agent's own identity. Endpoint readback retained Responses/Entra and added Activity/BotServiceRbac. The ordinary prompt agent's endpoint, identity and authentication remained unchanged.

The previous JSON-only experiment handler was not a chat interface. [channel.py](../hosted/channel.py) adds natural-language SDK turns and emits standard Responses MCP catalog/call items plus the final answer. The corrected version maps MCP `inputSchema` to Responses `input_schema`, retains tool UI metadata and includes the structured tool result in the MCP call output. A version-pinned direct smoke verified those fields and actual tool execution before the fresh client probes. This is a lab transport adapter, not an asserted native Activity-channel MCP Apps contract.

Initial `-a` prompts stopped at Foundry sign-in cards and later resumed. They are excluded from the fresh comparison: an adapter-schema correction and endpoint pin change occurred while authentication was pending. Cached-account sign-in completed without entering credentials or changing scopes.

| Published client | Fresh request sent (UTC) | Source MCP call (UTC) | Visible result |
| --- | --- | --- | --- |
| M365 Copilot, new conversation | 21:07:01 | 21:07:16 | Text-only rows/counter 1; no widget or Refresh |
| Teams, existing personal bot conversation | 21:07:40 | 21:07:48 | Text-only rows/counter 1; no widget or Refresh |

Run IDs were `hosted-m365-20261027-b` and `hosted-teams-20261027-b`. Screenshots were captured, opened and visually inspected. Source logs confirm both `show_table` calls; no `resources/read` appeared in the scoped 21:06:45-21:10:00 window. Model statements such as "Interactive MCP App displayed" were contradicted by the actual UI and are not rendering evidence.

The endpoint was pinned to corrected hosted version 7 throughout the fresh requests. **Exact served-version attribution remains limited, particularly for the reused Teams conversation:** session listing returned only older sessions and the available platform request logs did not expose a served version. No session reset, speculative permission change or additional prompt was used to hide this limitation. The evidence supports "the tested published hosted path returned text only", not "every hosted implementation is unsupported" or a fully version-matched negative test.

For communication: do not propose merely switching to hosted as a verified M365/Teams MCP Apps solution. The custom reference-browser pass and hosted automatic-offload findings remain valid, separate results.

## Large responses and offload

| Runtime | Input/result size | Observation |
| --- | --- | --- |
| Ordinary prompt, direct MCP | 256 KiB | No automatic file observed; initial/follow-up input usage 150,158/150,185 tokens. |
| Ordinary prompt, direct MCP | 1 MiB | `context_length_exceeded`. |
| Hosted Copilot SDK, native MCP through Toolbox | 1 KiB | Inline, no matching output file. |
| Hosted Copilot SDK, native MCP through Toolbox | 32 KiB | Automatic file; exact 32,768 bytes and SHA-256 verified; initial tool event replaced by an 813-byte notice/preview. |
| Hosted Copilot SDK, native MCP through Toolbox | 256 KiB | Automatic files; exact 262,144 bytes and SHA-256 verified; initial tool notices/previews 814 bytes. |
| Foundry-managed Copilot prompt harness | No inference | Creation refused with explicit subscription-enablement HTTP 403. |

The hosted test did not set `large_output`, pre-save payloads on the MCP server, or implement an offload wrapper. Model write/shell permissions were denied. Harness-created payload files were distinguished from the test's own JSONL evidence.

Both offloaded cases answered BEGIN/MIDDLE correctly and retrieved a previously withheld END marker without another MCP call in the follow-up. However, the model attempted a full-file read; the 256-KiB initial turn refetched once before selective `grep`. Therefore **automatic initial offload is proven; consistently minimal context usage is not**. The exact threshold and persistence after sandbox eviction were not measured.

The [CLI changelog](https://github.com/github/copilot-cli/blob/main/changelog.md#00376---2026-01-08) documents large-output files. The hosted measurements establish remote-MCP behavior for the tested SDK runtime; neither source establishes Foundry-managed harness defaults.

## Skills and tool discovery

The search-enabled three-task runs used 2,051-2,067 input tokens versus 1,082-1,090 for the complete concise catalog. Search deferred definitions but did not reduce total input tokens in these small cases.

Toolbox listed skill metadata separately from bodies and delivered single-file bodies plus a multi-file archive. The ordinary prompt agent omitted the required hidden skill phrase in the MCP-backed and native-reference cases, including controlled header variants and a separate Central US project. A mixed Toolbox control kept a working lookup tool constant: versions 19/20 without downloaded-body preload omitted the phrase; version 18 with preload returned it.

This isolates delivery from consumption without proving an invisible runtime root cause. Microsoft's [shipping-skill sample](https://github.com/Azure/azure-sdk-for-python/blob/84df3628/sdk/ai/azure-ai-projects/samples/agents/tools/sample_toolbox_with_shipping_skill.py) explicitly downloads a skill into instructions. That works as preload, not proof of automatic progressive loading.

## Supported-region control

A separate Central US project corrected the original region mismatch against the [published harness-region policy](https://github.com/Azure/azure-dev/blob/e58b139228ac63c3abd152d8053d7a71d2f21d1d/cli/azd/extensions/azure.ai.agents/internal/cmd/harness-agent-regions.json). Ordinary inference worked. Both the historical `github_copilot_preview` pair and canonical `microsoft_copilot_preview` with `Foundry-Features: MicrosoftCopilot=V1Preview` returned explicit subscription-enablement HTTP 403. No managed-harness inference ran.

The separate hosted SDK agent did run in Central US. An East US 2 hosted candidate remained unready; no root cause or general regional restriction was established. Hosted container readiness and the managed prompt-harness subscription gate are different issues.

## Evidence and retained limits

Private evidence includes `hosted-offload-verified-assessment.json`, `hosted-ui-verified-assessment.json`, `hosted-native-apps-direct-result.json`, the native UI snapshots, `foundry-published-b-*`, `foundry-ui-negotiated-*` and `m365-anyapp-debug-comparison-correlated-*`. The [public structured record](observations.json) contains sanitized measurements; historical failures are not the current result.

The original publication and authentication restrictions were retained/restored. No customer message was sent. Lab resources remain available for review and may incur charges. Managed-harness access and its skill/offload behavior remain unverified. Hosted M365/Teams requests now have actual text-only observations, with the served-version qualification above; none establishes a universal product failure.
