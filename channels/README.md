# Additional M365 integration routes

These experiments distinguish the M365-facing integration from the agent runtime. A successful MCP call is not an MCP Apps rendering pass.

## Foundry-backed declarative MCP plugin

```text
M365 declarative agent and MCP Apps renderer
  -> authenticated remote MCP facade on Container Apps
    -> Foundry hosted agent Responses endpoint
      -> GitHub Copilot SDK model turn
        -> synthetic source MCP tool
```

[facade.py](facade.py) preserves the discovered tool catalog, tool UI metadata, structured tool results and UI resource reads. Its `tools/call` invokes `delegated_rpc` in [native_apps.py](../hosted/native_apps.py). That operation requires a real model turn to make exactly the requested tool call with unchanged arguments, then returns the original MCP result. Resource reads also pass through the hosted SDK; the facade has no direct-source HTML fallback.

The dedicated `caldova-foundry-mcp` Container App uses Entra token validation and the existing lab API scope. Its managed identity has project-scoped Foundry access. A new declarative-agent package and SSO registration are kept separate from the original direct-MCP control.

**Lab boundary:** downstream calls use the facade's managed identity, not delegated end-user authorization. The service only exposes synthetic fixtures. This is not a production multi-user authorization design. The model runs again for widget callbacks, so this is not a latency-optimized design.

The [template](facade.bicep) creates only the new facade in the existing lab environment. Its Docker build uses a dedicated allowlisted context. Private deployment state, registration IDs and packages live under ignored `.azure/`; raw test evidence lives under ignored `evidence/`.

```powershell
# From the repository root, using the existing isolated hosted dependencies.
hosted\.venv\Scripts\python.exe -m unittest channels.test_facade -v
hosted\.venv\Scripts\python.exe -m unittest discover -s hosted -p test_main.py -v
.\.venv\Scripts\python.exe -m ruff check channels\facade.py channels\test_facade.py hosted
```

The API control verified unauthenticated rejection, discovery of 26 tools, a real Foundry-backed `show_table` result, and retrieval of the HTML resource. Subsequent actual tests in M365 Copilot web and Copilot inside Teams rendered the widget; real Refresh clicks advanced counter 1 to 2 in each. See the [conditions and client evidence](../docs/results.md#additional-m365-and-teams-pathways).

Initial M365 discovery requests reached the facade, but took 45-53 seconds waiting for a cold hosted SDK and exceeded the client's discovery deadline. The corrected facade loads a catalog snapshot from the hosted SDK before accepting traffic and keeps one replica running. The snapshot refreshes at facade startup/redeployment, not automatically on every upstream catalog change. Corrected discovery measured 0.188 seconds in one control; this is not a general performance benchmark.

The M365 pass used temporary **Any Teams app** applicability on the new auth registration, with the home-tenant restriction and exact single-user deployment retained. The original SpecificApp binding was restored and verified afterward. Neither a working SpecificApp configuration nor production multi-user authorization was established.

## Other routes

Custom SDK proxy and embedded Teams-tab implementations, where present, have their own subdirectories and isolated deployment state. Copilot Studio configuration is a separate low-code route. Do not infer their results from the facade's protocol checks or the earlier reference-browser pass.
