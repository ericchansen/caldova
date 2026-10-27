# Foundry capability test results

**Current checkpoint: October 27, 2026.** These are synthetic lab observations, not a general availability or support guarantee. The [sanitized record](observations.json) separates current outcomes from historical diagnostics. Raw service responses and UI evidence remain private.

**Bottom line:** a Foundry-hosted GitHub Copilot SDK agent can support an MCP Apps consumer through the SDK's experimental native APIs and a generic transport adapter. The ordinary Foundry prompt-agent route did not render Apps. Toolbox forwarded tool calls but failed to retrieve their advertised HTML resource. Automatic large-result offload was verified in the hosted SDK, not in the subscription-gated Foundry-managed Copilot harness.

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
| Hosted SDK agent -> published Teams/M365 channel | NOT TESTED | The custom reference consumer does not establish support in those channels. |
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

The original publication and authentication restrictions were retained/restored. No customer message was sent. Lab resources remain available for review and may incur charges. Managed-harness access, its skill/offload behavior, and hosted publication to Teams/M365 remain unverified; none should be silently converted into a pass or a universal failure.
