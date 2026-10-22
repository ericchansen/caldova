# Foundry capability test results

These are observations from this lab, not a general availability or support guarantee. The baseline used an ordinary Prompt Agent with `harness` omitted, `gpt-5-mini` version `2025-08-07`, and a synthetic authenticated MCP server.

All measurements and outcome summaries below have a [sanitized machine-readable evidence record](observations.json). Raw tenant-specific responses remain in ignored local evidence files.

## Answers

| Question | Result | Evidence and boundary |
| --- | --- | --- |
| Progressive tool discovery/search | PASS | The same 26-tool catalog becomes `tool_search` and `call_tool` when search is enabled. Three fresh tasks invoked both meta-tools and returned the correct records. The full-catalog control also passed. |
| Progressive skill discovery/loading | PARTIAL | Toolbox exposed skill metadata, separate `SKILL.md` content, and a multi-file archive. Hidden body markers were absent from discovery metadata and present in subsequent resource reads. The ordinary Prompt Agent did not load/use the orchard skill through MCP; it also failed to use an explicitly attached native skill reference. Do not equate Toolbox delivery with automatic runtime support. |
| MCP Apps in Copilot/Teams | BLOCKED; proxy defect observed | Direct MCP serves UI metadata, structured results, and the HTML resource. Toolbox preserves the UI URI but rejects reading that URI. Actual Copilot/Teams rendering remains untested because browser sign-in and positive-control registration are blocked. |
| Automatic spill-to-disk | NOT OBSERVED in ordinary agent; managed comparison BLOCKED | A 256-KiB response consumed 150,158 input tokens and its follow-up consumed 150,185. A 1-MiB response failed with `context_length_exceeded`. No harness-created file or selective file read appeared in exposed output. Managed Copilot harness creation was explicitly refused for the subscription. |

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

Personal publishing of the ordinary agent version 7 was accepted. Readback verified that the endpoint retained Responses, enabled Activity, retained Entra authentication, added `BotServiceRbac`, and pinned all traffic to that version. The downloaded app package matched the bot identity.

However, endpoint publication status still read `not_published`, and a catalog read returned HTTP 403. Store visibility is therefore unverified. The declarative positive control is prepared but not registered: the Developer Portal API also returned HTTP 403, and no auth-configuration ID was invented. The observed dedicated Edge browser required sign-in; subsequent passive checks found its debug endpoint unavailable. No new login attempts were made after the user asked to stop them.

## Large-result observations

The server returned raw deterministic text with hidden markers at three positions. It did not return a file, URL, or summary. The agent was not instructed to write anything and had no Code Interpreter.

| Payload | Observed outcome |
| --- | --- |
| 1 KiB | Completed with all three correct values after increasing the output allowance; same-response follow-up also returned the correct final marker. |
| 32 KiB | The tool call completed; the model exhausted output allowances of 1,500 and 4,096 tokens. This is an output-budget confound, not proof of context overflow. |
| 256 KiB | All three markers and the follow-up were correct; 150,158 then 150,185 input tokens were reported. |
| 1 MiB | HTTP 400 with `context_length_exceeded`. |

These results are consistent with ordinary tool output entering context rather than being automatically offloaded in this configuration. They do not reveal all internal service behavior, establish a universal offload threshold, or answer how the inaccessible managed Copilot harness behaves.

## Evidence and continuation

Raw requests, service responses, protocol discovery, assessments, and publication checks are preserved locally under ignored `evidence/`. They include tenant-specific IDs and are not published in this repository. Representative files:

- `mcp-caldova-catalog-discovery.json`, `mcp-caldova-search-discovery.json`
- `discovery-caldova-search-*-assessment.json`, `discovery-caldova-catalog-*-assessment.json`
- `mcp-caldova-skills-discovery*.json`, `mcp-caldova-skills-resource-*.json`
- `native-skill-config.json`, `native-skill-inspection.json`
- `mcp-direct-auth-control.json`, `toolbox-ui-resource.json`
- `spill-caldova-prompt-*.json`
- `create-caldova-copilot.json`, `m365-*.json`

To close the remaining questions: obtain managed-harness subscription enablement, complete one authorized Caldova browser sign-in and the MCP plugin's Entra SSO registration, then run the same fixture and verify an actual widget refresh in each host. [M365 continuation instructions](../m365/README.md) distinguish publication from rendering.

No customer email was sent by this lab, no existing Foundry resources were modified, and the test resources are retained for review.
