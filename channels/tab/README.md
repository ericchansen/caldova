# Authenticated Teams MCP Apps tab

A bounded synthetic personal Teams tab: Teams SSO authenticates the user,
an owned backend invokes the hosted Foundry SDK/model, and the official
`@modelcontextprotocol/ext-apps` AppBridge renders the source App in a
separate-origin double-iframe sandbox. This is not native M365 chat rendering.

## Private configuration and artifacts

No tenant IDs, deployed hostnames, registry identifiers, generated manifest, or
package ZIP belongs in publishable source. Public Microsoft Teams/CLI client IDs
and public documentation/service endpoints are protocol configuration, not
tenant-specific identifiers.

Private artifacts are ignored by the repository's `.azure/.gitignore`:

| Artifact | Path |
| --- | --- |
| Teams package | `.azure/tab-personal-app.zip` |
| Generated manifest and icons | `.azure/evidence/tab-package/` |
| Identity, origins and package state | `.azure/evidence/tab-state.json` |
| Exact UI handoff and observed results | `.azure/evidence/tab-handoff.md` |
| Deployment inputs | `.azure/evidence/tab-deploy-config.json` |
| Smoke and deployment evidence | `.azure/evidence/tab-*` |

The tab `.gitignore` also excludes legacy `package/`, all ZIPs, `dist/`,
`node_modules/`, generated manifests/parameters, environment files and caches.
Do not force-add these files.

`provision_identity.py` reads private deployment inputs:
`resource_group`, `environment_name`, `identity_name`, `registry_name`,
`tab_name`, `sandbox_name`, `location`, and `project_resource_id`.
It derives the environment's domain from Azure, not a source-code constant.
`tab.bicep` takes corresponding resource names as parameters.

Server configuration comes from `TAB_TENANT_ID`, `TAB_APP_ID`, `TAB_ORIGIN`,
`SANDBOX_ORIGIN`, `HOSTED_PROJECT_ENDPOINT`, `AZURE_CLIENT_ID`, and optional
`TAB_DIAGNOSTIC_CLIENTS`. `TAB_MODE` selects host or sandbox. The sandbox
server inserts the expected host origin into its HTML at request time; it
does not trust a caller-supplied referrer or query string to choose that origin.
The default example origins intentionally cannot target a real deployment.

## Authentication and execution

The backend validates the delegated token's signature, exact tenant/issuer/
audience, lifetime, scope, client, and user OID. Tokens are never stored or passed
to the App frame. There are no anonymous data endpoints or test-auth bypasses.

The backend uses a dedicated managed identity for the hosted `delegated_rpc`
route. Tool calls execute the hosted model/tool path; discovery/resource reads
use the native SDK APIs. This is **application identity downstream, not user
OBO**. Only the bounded synthetic fixture is authorized. Backend permissions
are limited to the selected Foundry project and registry image pulls.

The source resource URI, MIME type, HTML and CSP metadata are preserved. The
sandbox has a separate origin, restricted HTTP CSP and no runtime managed
identity access. Unknown CSP/device requirements fail closed.

## UI evidence criteria

`app-initialized` is emitted after **AppBridge.oninitialized**: the inner MCP
App handshake, not just Teams shell readiness or sandbox proxy readiness.
The initial tool call/result delivery follows this marker.

Passing UI evidence requires:

1. Successful Teams `getAuthToken` in the intended authenticated host.
2. A visibly rendered **source widget**, not merely the outer shell.
3. A real click on **Refresh inside that widget**.
4. The visible counter increasing, with correlated backend/hosted completion.

Neither a CLI-authenticated backend smoke test nor an initialization/completion
log marker alone proves visible widget rendering or successful UI Refresh.
Follow the private handoff for package installation and exact URLs. Never paste
tokens or weaken tenant policy to clear an authentication failure.

## Observed embedded-client result

**PASS — actual Teams web personal-tab rendering and App Refresh**, reported
by the retained UI worker on 2026-10-29 at 00:22 UTC after the readiness fix.
The source table was visibly rendered with counter **1**. The worker clicked
**Refresh inside the source widget**, then observed counter **2**. This was
not inferred solely from an initialization marker or backend smoke test.

The final captured App text confirms counter 2; the worker captured and opened
before/after screenshots. Exact run/request identifiers, timestamps and private
evidence references are recorded in `.azure/evidence/tab-handoff.md`.
The coordinator is responsible for the additional source-log correlation and
combined findings.

This result is limited to the tested **authenticated custom Teams embedded
client**, with official AppBridge rendering and the configured Foundry-backed
route. It does **not** establish native Teams/M365 chat rendering, support in
other clients, or general MCP Apps compatibility.

## Local checks

From the worktree root:

```powershell
python -m ruff check channels/tab
Set-Location channels/tab
npm test
npm run build
```

`npm run build` includes `tsc --noEmit` and Vite. Use `npm ci --no-audit --no-fund`
first if dependencies are absent. The schema check can be run against the
private generated manifest without regenerating its package.

`npm test` runs Python backend tests and four deterministic readiness tests.
The host permits up to 120 seconds for sandbox document startup plus the official
proxy-ready notification. An observed scale-to-zero startup took longer than the
old 30-second limit. The wait remains bounded and checks the exact frame source,
sandbox origin, and protocol method; iframe load alone never counts as readiness.
These timing tests are not browser-handshake or Teams-rendering evidence.

`python channels/tab/package_app.py` explicitly regenerates private package
artifacts. `python channels/tab/smoke.py` performs live authenticated operations;
it is not part of offline unit tests and does not validate the Teams UI.
Provision/build/deploy commands are not required to keep an existing deployment
available while UI investigation is paused.

## References

* [Teams tab SSO registration](https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-register-aad)
* [Official MCP Apps basic-host](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/basic-host)
