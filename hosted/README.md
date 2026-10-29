# Hosted MCP Apps and large-output experiments

This folder contains the actual Python code used in the Foundry hosted-agent experiments. It is a lab, not a production agent framework.

Later [M365-facing MCP facade and Teams-tab experiments](../channels/README.md) use this same hosted runtime and produced actual rendered/Refresh passes. They are separate from the built-in published-agent channel tests described below.

**Start here to understand the caller:** the [official MCP Apps reference host](https://github.com/modelcontextprotocol/ext-apps/blob/266a9e3b70dbd4a4f0546dda95da2a2c1a8be4b7/examples/basic-host/src/implementation.ts) calls the tool and reads its advertised UI resource. Its `initializeApp` function loads the HTML into a sandbox and supplies the tool result through `AppBridge`. The model does not render HTML.

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Browser consumer | Official `examples/basic-host`, pinned above | Discover tools, request a tool result and UI resource, render the iframe, forward widget interactions |
| Local transport adapter | [frontend_bridge.py](frontend_bridge.py) | Translate MCP requests into authenticated Foundry Responses requests |
| Hosted HTTP handler | [main.py](main.py), `respond` and `execute` | Dispatch the experiment operation and return its JSON result |
| Agent runtime | GitHub Copilot SDK 1.0.11 | Model orchestration and native MCP integration |
| Generic native MCP Apps operations | [native_apps.py](native_apps.py), `rpc` | Delegate tool discovery, app tool calls and UI resource reads to the SDK's MCP Apps APIs |

Microsoft Agent Framework was **not** used. The HTTP hosting library is `azure-ai-agentserver-responses==2.3.0`. Models are accessed with an Entra token provider, not an API key.

## Three distinct paths

### 1. Original single-tool workaround: `custom`

```text
Reference browser
  -> local MCP-to-Responses adapter
    -> Foundry hosted agent
       -> Copilot SDK tool handler -> Toolbox -> source MCP tool
       -> authenticated resource bridge ------> source MCP HTML
```

The initial proof was deliberately limited to `show_table` and `ui://caldova/table`. It preserves the raw `CallToolResult`, including `structuredContent`, instead of returning only the model's summary. **HTML bypasses Toolbox.** It is not proof of transparent MCP Apps forwarding through Toolbox.

In this mode, even Refresh runs a new model turn before calling the tool. That proves the hosted execution path but is not the recommended latency design for explicit UI actions.

### 2. Generic SDK-native path: `native-direct`

```text
Reference browser
  -> local transport adapter
    -> Foundry hosted agent
      -> Copilot SDK native MCP Apps APIs
        -> source MCP server
```

This path registers the server's catalog with the SDK rather than writing one Python wrapper per tool. The transport maps:

| Incoming MCP method | Native SDK operation |
| --- | --- |
| `tools/list` | `session.rpc.mcp.apps.list_tools` |
| `tools/call` | `session.rpc.mcp.apps.call_tool` |
| `resources/read` | `session.rpc.mcp.apps.read_resource` |
| `resources/list` | `session.rpc.mcp.resources.list`, filtered to advertised UI resources |

Tool names and UI URIs come from discovery. The adapter rejects unadvertised tools and resources. The SDK enforces app visibility and origin-server scoping. The lab's configured catalog is read-only, and its permission callback approves only read-only MCP requests from that server; this is not a production permission policy.

The SDK feature is **experimental and opt-in**: this sample supplies `enable_mcp_apps=True` and `COPILOT_MCP_APPS=true` to its own SDK runtime. This is not a Foundry managed-harness entitlement switch. The native API probe verified `capabilities.ui.mcpApps=true`, a 26-tool catalog, model-selected ordinary and UI tools, HTML retrieval, and an app-originated tool callback. A separate real browser test rendered the widget and advanced its counter from 1 to 2 with an actual iframe Refresh click.

The configured fixture has one UI tool. Multiple UI URIs are covered by adapter unit tests, but multiple live MCP servers, arbitrary customer apps, production authorization policies and large-catalog performance have not been validated.

### 3. Native SDK through Toolbox: `native-toolbox`

The same generic adapter points the SDK at the project-local Toolbox instead of the source server. There is **no resource fallback** in this mode. It is the negative comparison for Toolbox's advertised UI URI:

```text
No resource provider handles URI 'ui://caldova/table'.
```

Do not silently enable the `custom` path to turn this comparison into a pass.

## What ran in the hosted agent

The browser-facing calls use this request contract:

```json
{
  "input": "{\"operation\":\"native_rpc\",\"run_id\":\"catalog\",\"native_route\":\"direct\",\"rpc_method\":\"tools/list\"}",
  "stream": false
}
```

The URL is the hosted agent's dedicated endpoint:

```text
{project_endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1
```

`frontend_bridge.invoke` sends that request with an Entra token, requires a completed response, and decodes the JSON in its `output_text`. `respond` is the corresponding hosted entry point. This extra transport contract is application code, not an automatically generated Foundry MCP Apps endpoint.

For model selection rather than explicit UI tool calls, the `native_apps` probe uses `session.send_and_wait` with the full native MCP catalog and captures the actual SDK tool events. For widget-originated calls, the generic adapter uses the SDK's app tool-call API directly, without another model turn.

The later `delegated_rpc` operation runs a real SDK model turn for each requested tool call, checks that it made exactly that call with unchanged arguments, and returns the original structured result. The remote declarative facade and Teams tab use this operation to establish actual Foundry agent execution rather than only deterministic RPC dispatch. Their callbacks therefore also incur a model turn; the experiment is not latency-optimized.

### Published-channel probe

[channel.py](channel.py) accepts ordinary text rather than the JSON experiment envelope. It runs the native SDK model against direct MCP and emits Responses `mcp_list_tools`, `mcp_call` and message items. Tool descriptors retain `_meta.ui`; tool output contains the original structured result. It does not convert an MCP App into an Adaptive Card, host an external UI, or substitute the direct declarative plugin. Preserved metadata alone does not establish an Activity-channel rendering contract.

After verifying a natural-language request against the hosted Responses endpoint, publish only the isolated hosted experiment:

```powershell
.\.venv\Scripts\python.exe -m hosted.publish
```

The helper previews and creates `caldova-hosted-bot` with the existing parameterized Bicep template, verifies the generated package's identity, and requests `Shared` (Just you) publication. It retains Responses and Entra, adds Activity/BotServiceRbac through the publish API, and writes separate `.azure/hosted-m365-state.json`. It refuses an existing publication-state file instead of blindly submitting again. Existing ordinary-agent resources are not changed. Later hosted deployments retain the published protocols and authorization schemes.

Actual client tests must open **Caldova Hosted Lab** in M365 Copilot and in Teams personal bot chat, use distinct run IDs, and inspect widget rendering and a real Refresh separately from tool execution. Never use the local reference consumer as a substitute for these tests.

The completed October 27 client tests returned **text only in both clients**, despite real source MCP calls. No widget or Refresh control appeared. The endpoint was pinned to corrected version 7, but the available traces did not identify the exact served version for the existing Teams conversation. See the [complete channel evidence and qualification](../docs/results.md#hosted-publication-to-m365-and-teams). The custom-browser pass is not a verified published-channel solution.

## Observed large-output behavior

The `offload` operation uses the SDK's native remote-MCP connection to Toolbox. It does **not** register a replacement `large_result` handler and does not set `large_output`. The source fixture returns raw synthetic text and creates no files.

| Source result | Observed initial handling |
| --- | --- |
| 1 KiB | Inline; no matching output file |
| 32 KiB | Runtime-created `/tmp/...-copilot-tool-output-....txt`; file bytes and SHA-256 matched the source payload |
| 256 KiB | Same automatic offload behavior; exact payload file verified |

The 32/256-KiB MCP results were replaced by file-reference notices and previews of 813/814 bytes in the captured tool-completion events. No custom offload implementation was added. The application's own JSONL evidence files are separate and excluded from file detection.

**Offload does not guarantee low subsequent context usage.** The model requested a full-file read. In the 256-KiB first turn it also repeated the MCP call before switching to selective `grep`. The later END-marker request used the existing file without another MCP call. These are observed limitations, not a clean latency or token-efficiency benchmark. No exact offload threshold or persistence across sandbox eviction was established.

This proves behavior in the tested **hosted Copilot SDK runtime**, not in Foundry's gated `microsoft_copilot_preview` prompt-agent harness.

## Run and inspect the lab

### Prerequisites

- Provision the authenticated synthetic fixture and isolated control project using the [repository instructions](../README.md). Local `.azure/` state is intentionally not published.
- Create the project-local `caldova-mcp` connection with `ProjectManagedIdentity` authentication and the source API audience. Create `caldova-hosted-catalog` with that connection and the fixture MCP tool. Its published consumer endpoint is used by this experiment.
- Give the project identity image-pull permission on the lab registry. The tested registry uses legacy registry permissions and `AcrPull`.
- After the hosted identity exists, give it `Foundry User` at its model/Toolbox project and the synthetic API's `Mcp.Invoke` application role. The Toolbox connection's project identity also needs `Mcp.Invoke`. Do not replace authentication with anonymous access.

`deploy.py` assumes these resources and scoped permissions exist. It deploys only the separate `caldova-hosted-capabilities` agent; it does not provision infrastructure, install M365 apps or change the original prompt-agent publication.

### Local validation

Run from the repository root:

```powershell
python -m venv hosted\.venv
hosted\.venv\Scripts\python.exe -m pip install -r hosted\requirements.txt
hosted\.venv\Scripts\python.exe -m unittest discover -s hosted -p test_main.py -v
.\.venv\Scripts\python.exe -m ruff check hosted
```

The Docker build also runs the actual Linux Copilot executable and starts the HTTP server to verify `/readiness`.

### Build and deploy

```powershell
$lab = Get-Content .azure\lab.json -Raw | ConvertFrom-Json
$tag = "hosted-$(Get-Date -Format yyyyMMddHHmmss)"
Push-Location hosted
try {
  $build = az acr build --registry $lab.outputs.AZURE_CONTAINER_REGISTRY_NAME `
    --subscription $lab.subscription --image "caldova-hosted:$tag" `
    --platform linux/amd64 --file Dockerfile --no-logs --output json . |
    ConvertFrom-Json
  if ($LASTEXITCODE -ne 0) { throw "Image build failed" }
} finally {
  Pop-Location
}
$image = "$($build.outputImages[0].registry)/$($build.outputImages[0].repository)@$($build.outputImages[0].digest)"
.\.venv\Scripts\python.exe -m hosted.deploy --image $image
```

The deployment helper defaults to the existing Central US control state and writes `.azure/hosted-centralus-state.json`. It records the created version before polling, verifies the service's active status and Entra endpoint configuration, and never modifies `caldova-prompt`. Active metadata is not proof of successful model/tool execution; the separate smoke and live experiments establish that.

The tested Central US candidate ran. An East US 2 candidate remained unready; that does not establish a general regional restriction. The service rejected the legacy `v0.1.1` Responses protocol at invocation, so use the current `container_configuration` / `protocol_versions` contract with Responses `2.0.0`, as implemented here.

After deployment and permission setup, invoke the actual hosted model and then a bounded offload experiment. These calls incur model usage and retain private evidence under ignored `evidence/`:

```powershell
.\.venv\Scripts\python.exe -c "import asyncio; from hosted.frontend_bridge import invoke; print(asyncio.run(invoke('smoke'))['answer'])"
.\.venv\Scripts\python.exe -c "import asyncio; from hosted.frontend_bridge import invoke; r=asyncio.run(invoke('offload',run_id='offload-example',size_bytes=32768)); print(r['answer']); print(r['runtime_output_files'])"
```

The expected smoke answer is `HOSTED_COPILOT_READY`. For offload, inspect the captured events, file size/hash and follow-up answer, not just the final model text.

### Connect the reference consumer

Start one loopback adapter from the repository root:

```powershell
$env:CALDOVA_UI_PATH = "native-direct" # or custom / native-toolbox
$env:CALDOVA_UI_PORT = "8084"
$env:CALDOVA_HOSTED_STATE = ".azure\hosted-centralus-state.json"
.\.venv\Scripts\python.exe -m hosted.frontend_bridge
```

Run the official [basic-host example](https://github.com/modelcontextprotocol/ext-apps/tree/266a9e3b70dbd4a4f0546dda95da2a2c1a8be4b7/examples/basic-host) separately. Set its `SERVERS` environment variable to `["http://127.0.0.1:8084/mcp"]`. The adapter permits only the reference UI origin `http://localhost:8080`; its HTTP listener is loopback-only.

In the reference UI, select the native direct server, choose `show_table`, provide a fresh `run_id`, and call the tool. A pass requires the real widget, then a real Refresh callback and a corresponding server result. `lookup_orchards` is an ordinary-tool control in the same catalog.

The fixture's counter is process-local. After a scale-to-zero restart it resets; compare consecutive warm calls rather than assuming the counter survives idle periods.

## Limits

- The reference consumer is not the customer's application.
- Native SDK RPC support is experimental and still needs an MCP Apps renderer and transport integration.
- The custom single-tool workaround does not make Toolbox forward HTML resources.
- The hosted agent's published M365/Teams tests returned text only; no native MCP Apps channel pass was established.
- The default Foundry prompt harness and the Foundry-managed Copilot harness are different from this hosted SDK runtime.
- Raw evidence, tenant configuration, screenshots and tokens must not be committed.
