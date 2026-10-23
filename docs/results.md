# Foundry capability test results

These are observations from this lab, not a general availability or support guarantee. The baseline used an ordinary Prompt Agent with `harness` omitted, `gpt-5-mini` version `2025-08-07`, and a synthetic authenticated MCP server.

All measurements and outcome summaries below have a [sanitized machine-readable evidence record](observations.json). Raw tenant-specific responses remain in ignored local evidence files.

## Answers

| Question | Result | Evidence and boundary |
| --- | --- | --- |
| Progressive tool discovery/search | PASS | The same 26-tool catalog becomes `tool_search` and `call_tool` when search is enabled. Three fresh tasks invoked both meta-tools and returned the correct records. The full-catalog control also passed. |
| Progressive skill discovery/loading | Delivery PASS; ordinary skill-use cases FAIL | Toolbox exposed metadata and separate content. On a fixed Toolbox agent version, both recorded outer-inference-header variants failed to return the required marker; a native-reference case with the preview header also failed. A client retrieved the skill with or without that header. The runtime cause and supported ordinary-agent integration contract remain unresolved; managed-harness comparison is BLOCKED. |
| MCP Apps in Copilot/Teams | INDETERMINATE; proxy defect observed | Direct MCP serves UI metadata, structured results, and the HTML resource. Toolbox preserves the UI URI but rejects reading that URI. Both hosts show the published Foundry agent. After correcting its Activity URL, Copilot delivered an authorization card and then a service content-filter error. The deployed declarative control answered but reported its connector unavailable. Neither route has passed widget rendering and refresh. |
| Automatic spill-to-disk | INDETERMINATE; managed comparison BLOCKED | Offload was not observed in the ordinary agent. A 256-KiB response consumed 150,158 input tokens and its follow-up consumed 150,185. A 1-MiB response failed with `context_length_exceeded`. No harness-created file or selective file read appeared in exposed output. Managed Copilot harness creation was explicitly refused for the subscription. |

The small fixture catalog did **not** demonstrate a total-token saving: the search-enabled three-task runs used 2,051-2,067 input tokens each versus 1,082-1,090 with the complete, concise catalog. Search adds a round-trip; its demonstrated benefit here is deferred definitions, not a measured cost reduction.

## Managed harness availability

The creation API first required:

```text
Foundry-Features: GitHubCopilot=V1Preview
```

After that documented-by-service opt-in was supplied, the request returned HTTP 403:

```text
Agent creation with kind 'prompt' and harness type 'github_copilot_preview' is not enabled for this subscription.
```

The ordinary agent was created and completed an actual inference request. No substitute harness, other subscription, or custom persistence middleware was used to bypass the preview gate. Microsoft's [managed-harness authoring guidance](https://github.com/microsoft/azure-skills/blob/main/skills/microsoft-foundry/foundry-agent/create/create-managed-harness.md) establishes how to request the feature, not whether a particular subscription has it.

## Skill evidence

The Toolbox exposed three single-file skills and one multi-file skill. `resources/list` advertised their names and descriptions; separate `resources/read` requests retrieved their body markers. The multi-file package was also available as `skill://caldova-reference.zip`.

With the skills-only Toolbox attached as an MCP tool, the ordinary Prompt Agent received an empty `mcp_list_tools` item and said the requested inspection skill was unavailable. An unrelated greeting returned normally. A separate native `skills`-reference configuration was accepted and preserved in the agent definition, but the run did not produce the hidden phrase or a skill-load event.

This establishes successful resource delivery, not automatic skill loading in every Prompt Agent harness. Supplementary content was retrieved as an archive; independent file selection by the managed Copilot harness could not be tested because that harness is gated.

### Follow-up diagnosis

The follow-up pinned Toolbox version 3 and orchard skill version 2. A protocol client successfully listed resources and read the orchard body both with and without `Foundry-Features: Skills=V1Preview`; discovery metadata did not contain the marker. Both variants returned zero tools and six resources.

Two fresh inference requests used the same immutable ordinary agent version 13 and task, varying only that outer request header. Both completed but omitted the required marker, each reporting 55 input tokens. A native-reference request against version 14, with the preview header explicitly recorded, also completed without the marker and reported 38 input tokens. Separately supplying the body inline succeeded; that confirms the model can follow the content, not that skill loading works.

These are **failed functional cases**, not passing tests merely because failure was predicted. They narrow the investigation beyond storage and this outer-header toggle. They do not prove that no internal resource read occurred, that the header is irrelevant at every boundary, or that ordinary agents universally lack skills. The remaining question for the Foundry owner is whether these ordinary-agent attachment paths implement skill consumption, and, if supported, which contract or runtime trace identifies the missing prerequisite or defect. No custom resource-to-tool adapter was introduced to disguise a native integration failure.

The recorded-header probes and live definition readbacks are the comparison evidence. A separate check of the actual `agent_endpoint` verified version 7 at 100% with Responses, Activity, Entra, and BotServiceRbac unchanged.

### Isolating the consuming runtime

Microsoft's [Prompt Agent shipping-skill sample](https://github.com/Azure/azure-sdk-for-python/blob/84df3628/sdk/ai/azure-ai-projects/samples/agents/tools/sample_toolbox_with_shipping_skill.py) explicitly downloads the skill and inserts its content into agent instructions. That is preloading, not automatic progressive consumption through MCP. Its comment saying Prompt Agents have no native skill-reference field is in tension with the newer [agent schema](https://github.com/Azure/azure-rest-api-specs/blob/2927d4ca/specification/ai-foundry/data-plane/Foundry/src/agents/models.tsp), which declares `PromptAgentDefinition.skills`. Neither source alone settles the native runtime's behavior.

A stronger control put the same orchard skill beside a working authenticated MCP lookup tool in Toolbox version 4. All cases used the same task and one permitted lookup tool; the inline control alone received the previously retrieved skill body in its instructions.

| Ordinary-agent configuration | Version | Lookup succeeds | Required skill phrase returned |
| --- | --- | --- | --- |
| Toolbox plus downloaded-body preload | 18 | Yes | Yes |
| Same Toolbox without preload | 19 | Yes | No |
| Same Toolbox plus native skill reference | 20 | Yes | No |

All three responses completed. This rules out an empty tool catalog or broken generic tool invocation as sufficient explanations for these failures. It isolates the missing behavior to making the skill usable by the consuming runtime; resource-specific authorization and hidden runtime processing are still not visible. The working preload is an honest alternative for applying instructions, not a substitute for proving progressive discovery. An earlier unrestricted-tool attempt made unrelated tool calls and is excluded from this controlled comparison.

The sample-style skills-only Toolbox with a configured search entrypoint (version 5) still returned zero callable tools and two skill resources. No agent inference was run against that configuration. Adding the search definition did not expose a callable skill loader in that observed protocol surface.

## MCP Apps evidence

The direct server passed authenticated protocol checks:

- Unauthenticated MCP requests returned HTTP 401.
- An authenticated client listed all 26 tools.
- `show_table` returned a per-run identifier, counter, and synthetic rows.
- `resources/read` retrieved the HTML at `ui://caldova/table`.

The Toolbox's tool descriptor retained `_meta.ui.resourceUri`, but reading the same resource through the Toolbox returned:

```text
No resource provider handles URI 'ui://caldova/table'.
```

That is a concrete failure of the tested Toolbox resource route. It does **not** prove that direct-MCP tools on a Foundry agent cannot render through the Microsoft 365 channel.

A separate direct-MCP `show_table` request through ordinary agent version 7 completed successfully. However, its exposed Responses payload contained neither `ui://caldova/table` nor a structured-content field: the listed tool retained name, description, input schema, and annotations, and the final message was `output_text`. This identifies an additional visible metadata boundary before the UI channel. It does not reveal out-of-band Activity metadata or establish whether a particular host rendered a widget.

Personal publishing of the ordinary agent version 7 was accepted. Readback verified that the endpoint retained Responses, enabled Activity, retained Entra authentication, added `BotServiceRbac`, and pinned all traffic to that version. The downloaded app package matched the bot identity.

The authenticated browser subsequently verified the ordinary agent's catalog visibility and opened it in both Microsoft 365 Copilot and Teams personal chat. This supersedes the earlier inconclusive endpoint publication status and HTTP 403 catalog read. These are two client surfaces of the same Foundry agent, not different agent runtimes.

Initial blank responses and timeouts preceded correction of a lab configuration defect: the bot messaging URL lacked `?api-version=2025-05-15-preview`. A direct request without that query returned "Missing required query parameter: api-version"; the corrected URL reached Activity payload parsing. The helper and deployed bot were corrected and read back against [Microsoft's publishing implementation](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/internal/pkg/botservice/botservice.go). Those earlier UI failures are excluded from MCP Apps support conclusions; this does not establish that the missing query was their only cause.

After correction, Copilot displayed the Foundry sign-in card. Selecting the already signed-in test account returned to the conversation without credentials or MFA. A subsequent exact-marker greeting returned `invalid_request_error` with `content_filter` on the prompt. The channel therefore delivered a service error, rather than remaining blank. A new ordinary widget probe could not be submitted with verified input focus, so there is no post-correction widget result. No content filters were changed.

The declarative MCP Apps control completed Entra SSO registration and Developer Portal validation/import. Teams personal sideloading was denied with "Uploading custom apps is not allowed." Separately, the supported [administrator upload route](https://learn.microsoft.com/microsoft-365/admin/manage/agent-registry?view=o365-worldwide#upload-custom-agent) deployed the control with both Publish and Install restricted to the single test user and the Default policy template retained. No sideload or security policy was relaxed.

The control opened through its actual Copilot catalog entry after one refresh. Its configured starter, sent at `2026-10-22T22:47:12Z` with `run_id=control-first`, produced an answer saying the connector/tool was unavailable; no connector sign-in card appeared. Application console logs contained no matching run ID, MCP POST/GET, tool discovery/call, resource read, auth-rejection, or well-known metadata event from 22:45 through the verified log watermark of 22:49:29 UTC. This is no observed server-side MCP attempt, not proof that discovery or authorization was never attempted upstream. The earlier load error is historical; this is not a rendering pass.

A bounded diagnostic updated the same governed control to version `1.0.1`, pinning only `show_table` using its actual authenticated schema and retaining UI metadata, authentication, the single-user audience, and the default policy. The host's changed conversation starter confirmed the updated configuration before `control-pinned` was sent at `2026-10-22T22:56:58Z`. It again answered that the tool was unavailable, with no widget, sign-in, or connector-consent card. The final outcome is recorded in a native accessibility snapshot; screenshot capture was refused because the window was not foreground. A separate successful health probe refreshed the server logs through 22:59:31 UTC. The window starting at 22:56 contained no matching run ID or MCP, tool, resource, auth-rejection, or metadata event. This remains application-server evidence, not visibility into upstream discovery, authorization, or ingress failures. Neither the dynamic nor pinned control establishes host rendering support or non-support.

Separate direct-API no-tool diagnostics completed in 35.69 seconds on version 7 and 2.70 seconds on the no-tools version 1. These single runs are not a benchmark or causal comparison. A temporary version-1 channel control was never submitted because input focus could not be verified; version 7 was restored and read back. A version-7 warm UI retry overlapped the pin change and is excluded from matched-version comparisons.

Existing policy-managed Foundry diagnostic settings were readable without changing logging or permissions. The post-authentication channel window contains a `Projects_Wildcard_Post` with HTTP 202 followed by a `create_response` with HTTP 400 sharing the same correlation ID. The model/deployment is `gpt-5-mini`, version `2025-08-07`, also used by the successful direct requests. This locates a correlated model-service failure after the accepted project request; it does not identify the rejected prompt content or a separate channel filter. The queried logs expose metadata, not the full prompt or filter category; safety metrics did not provide usable category data for the window. A scoped Entra sign-in query also succeeded but returned no matching MCP-resource events. Absent events are not proof that no upstream authorization attempt occurred. The declarative control remains a separate M365 plugin-to-MCP path, not the Foundry bot path.

Further SSO checks verified the registered identifier URI, delegated scope, token-store preauthorization, and consent redirect. The existing operator obtained a token for the SSO resource alias, and the MCP server accepted it and listed 26 tools. Its v2 audience was the existing application ID, which the verifier already accepts. This is an operator control, not proof that the M365 token store obtains or sends the same token. Subsequent explicitly noninteractive sign-in queries were throttled (HTTP 429); their absence cannot be treated as a negative authentication result.

There is a concrete app-binding compatibility lead: the [OAuth/MCP guide](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-oauth#use-the-teams-developer-portal) warns that restricting a registration to a specific Teams app can cause 404s because Copilot does not resolve that ID for MCP calls. The [Entra SSO guide](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso#use-the-teams-developer-portal) still describes app binding. Saved post-save values confirm that this lab's registration is specifically bound to the intended app, with the correct base URL and scope. Applicability of the OAuth warning to this SSO configuration is unproven. A temporary Any-Teams-app test was not authorized; the binding remains unchanged.

A subsequent safe-input check and a [documented bot-chat prefill deep link](https://learn.microsoft.com/microsoftteams/platform/concepts/build-and-test/deep-link-teams#deep-link-to-navigate-to-chat-messages) did not produce a verified composer value. Nothing was typed globally or sent. These are operational input failures, not additional model or MCP Apps outcomes.

## Large-result observations

The server returned raw deterministic text with hidden markers at three positions. It did not return a file, URL, or summary. The agent was not instructed to write anything and had no Code Interpreter.

| Payload | Observed outcome |
| --- | --- |
| 1 KiB | Completed with all three correct values after increasing the output allowance; same-response follow-up also returned the correct final marker. |
| 32 KiB | The original extraction request exhausted output allowances of 1,500 and 4,096 tokens. A revised compact extraction request on direct-MCP version 7 completed with 19,748 input and 346 output tokens; the withheld-END follow-up was correct with 19,778 input and 174 output tokens and no payload refetch. |
| 256 KiB | All three markers and the follow-up were correct; 150,158 then 150,185 input tokens were reported. |
| 1 MiB | HTTP 400 with `context_length_exceeded`. |

These results are consistent with ordinary tool output entering context rather than being automatically offloaded in this configuration. They do not reveal all internal service behavior, establish a universal offload threshold, or answer how the inaccessible managed Copilot harness behaves.

The revised task requests only the 24-character BEGIN and MIDDLE values, then asks for the previously unreported END value. Exact output shape, completion, and absence of a new `large_result` call are checked; finding marker substrings inside an oversized answer is no longer sufficient. The successful direct-route run retained the 4,096-token initial allowance. The fixture already has newline-delimited markers, so no delimiter defect or universal inability to parse them is established. This resolves the 32-KiB extraction failure for the revised task, not the hidden storage mechanism.

Separate version-9 Toolbox exploration is excluded from the direct-route comparison. The revised runner was exercised against verified version 7, with publication and local deployment state unchanged. Original follow-ups requested a value already present in the preceding answer; they establish less about payload retention than the new withheld-value case.

## Evidence and continuation

Raw requests, service responses, protocol discovery, assessments, and publication checks are preserved locally under ignored `evidence/`. They include tenant-specific IDs and are not published in this repository. Representative files:

- `mcp-caldova-catalog-discovery.json`, `mcp-caldova-search-discovery.json`
- `discovery-caldova-search-*-assessment.json`, `discovery-caldova-catalog-*-assessment.json`
- `mcp-caldova-skills-discovery*.json`, `mcp-caldova-skills-resource-*.json`
- `native-skill-config.json`, `native-skill-inspection.json`
- `mcp-direct-auth-control.json`, `toolbox-ui-resource.json`
- `spill-caldova-prompt-*.json`
- `create-caldova-copilot.json`, `m365-*.json`
- `activity-route-without-version.json`, `activity-route-with-reference-version.json`
- `control-first-server-log.json`, `control-discovery-wire-events.json`, `control-first-log-freshness.json`
- `control-pinned-post-health-log-counts.json`, `control-pinned-health-freshness-probe.json`
- `channel-control-restore7-readback.json`, `published-ui-api-greeting-assessment.json`, `channel-control-v1-api-assessment.json`
- `skill-contract-*-request.json`, `skill-contract-*-assessment.json`, `skill-contract-summary.json`
- `skill-contract-protocol-header-off.json`, `skill-contract-protocol-header-on.json`
- `compact-spill-coordinator-assessment.json`, `budget-coordinator-tool-differences.json`
- `diagnosis-foundry-channel-log-summary.json`, `diagnosis-channel-model-comparison.json`, `diagnosis-control-signin-read.json`
- `bounded-mixed-summary.json`, `skill-search-entrypoint-discovery.json`
- `ui-metadata-direct-foundry-assessment.json`
- `diagnosis-sso-effective-app-contract.json`, `diagnosis-sso-alias-mcp-auth-control.json`

To close the remaining questions: obtain the supported ordinary-agent skill-consumption contract or product-side trace for the failed cases; obtain managed-harness subscription enablement; resolve the control's unavailable connector without relaxing security; and submit a benign ordinary-agent widget probe through the corrected channel when safe input is available. Verify actual widget rendering and a refresh round-trip separately in each host. Browser authentication and control registration are no longer the outstanding prerequisites. Managed access blocks only managed cases, not independent ordinary-agent investigations. [M365 continuation instructions](../m365/README.md) distinguish publication from rendering.

No customer email was sent by this lab, no existing Foundry resources were modified, and the test resources are retained for review.
