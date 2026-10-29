import { app, authentication } from "@microsoft/teams-js";
import {
  AppBridge, PostMessageTransport, RESOURCE_MIME_TYPE, getToolUiResourceUri,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import "./style.css";
import { loadSandboxProxy } from "./sandbox-readiness";

const status = document.querySelector<HTMLParagraphElement>("#status")!;
const evidence = document.querySelector<HTMLPreElement>("#evidence")!;
const button = document.querySelector<HTMLButtonElement>("#connect")!;
const log = (phase: string, data: unknown = {}) => {
  evidence.textContent += JSON.stringify({ time: new Date().toISOString(), phase, data }) + "\n";
};
let bridge: AppBridge | undefined;
let teamsReady = false;
const timed = <T>(promise: Promise<T>, ms: number, label: string): Promise<T> =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} timed out`)), ms);
    promise.then(value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); });
  });

// Tokens exist only in this closure while a request is made. No storage or iframe transfer.
async function api(method: string, fields: Record<string, unknown> = {}) {
  const token = await timed(authentication.getAuthToken(), 45000, "Teams SSO");
  const response = await fetch("/api/rpc", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ method, ...fields }),
    signal: AbortSignal.timeout(210000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(result)}`);
  log(method, {
    requestId: response.headers.get("X-Request-ID"),
    structuredContent: result.structuredContent,
  });
  return result;
}

button.onclick = async () => {
  button.disabled = true;
  evidence.textContent = "";
  try {
    if (!teamsReady) {
      await timed(app.initialize(), 15000, "Teams initialization");
      teamsReady = true;
    }
    const context = await app.getContext();
    log("teams-context", { host: context.app.host.name, client: context.app.host.clientType });
    status.textContent = "Authenticating with Teams and discovering the hosted MCP App…";
    const config = await (await fetch("/config")).json();
    const catalog = await api("tools/list");
    const tool = catalog.tools.find((item: { name: string }) => item.name === "show_table");
    if (!tool) throw new Error("Hosted SDK did not advertise the allowed show_table App.");
    const uri = getToolUiResourceUri(tool);
    if (uri !== "ui://caldova/table") throw new Error("Unexpected resource contract.");
    const resource = await api("resources/read", { uri });
    const content = resource.contents.find((item: { uri: string; mimeType: string }) =>
      item.uri === uri && item.mimeType === RESOURCE_MIME_TYPE);
    if (!content || typeof content.text !== "string") throw new Error("MCP App HTML not returned.");
    // Use the read-resource metadata; never replace or synthesize resource HTML.
    const ui = content._meta?.ui;
    if (!ui?.csp) throw new Error("Source resource did not preserve its CSP metadata.");
    log("resource-contract", { uri, mimeType: content.mimeType, meta: content._meta });
    await bridge?.close();
    const iframe = document.createElement("iframe");
    iframe.title = "Caldova synthetic MCP App";
    iframe.setAttribute("sandbox", "allow-scripts allow-same-origin");
    document.querySelector("#app")!.replaceChildren(iframe);
    const sandboxUrl = new URL("/sandbox.html", config.sandboxOrigin);
    if (sandboxUrl.origin === location.origin) throw new Error("Sandbox must have a separate origin.");
    sandboxUrl.searchParams.set("csp", JSON.stringify(ui.csp));
    status.textContent = "Waiting for the isolated sandbox (cold startup may take up to 120 seconds)…";
    const sandboxStarted = performance.now();
    await loadSandboxProxy(iframe, sandboxUrl);
    log("sandbox-proxy-ready", { elapsedMs: Math.round(performance.now() - sandboxStarted) });
    const runId = `tab-${crypto.randomUUID().replaceAll("-", "")}`;
    bridge = new AppBridge(null, { name: "caldova-teams-tab", version: "0.1.0" }, {
      serverTools: {}, serverResources: {},
    }, { hostContext: { theme: "light", platform: "web", displayMode: "inline",
      availableDisplayModes: ["inline"], containerDimensions: { width: iframe.clientWidth, maxHeight: 1600 } } });
    bridge.oncalltool = async params => {
      if (params.name !== tool.name || params.arguments?.run_id !== runId ||
          Object.keys(params.arguments ?? {}).some(key => key !== "run_id")) {
        throw new Error("App callback outside the originating tool/run is not allowed.");
      }
      status.textContent = "App Refresh → authenticated backend → Foundry model turn…";
      const result = await api("tools/call", { name: params.name, arguments: params.arguments });
      status.textContent = `App callback completed; source counter ${result.structuredContent?.counter}.`;
      log("app-refresh-completed", { runId, counter: result.structuredContent?.counter });
      return result;
    };
    bridge.onreadresource = params => {
      if (params.uri !== uri) throw new Error("Resource outside this App is not allowed.");
      return api("resources/read", { uri });
    };
    bridge.onlistresources = () => api("resources/list");
    bridge.onsizechange = ({ height }) => {
      if (height && Number.isFinite(height)) iframe.style.height = `${Math.min(1600, Math.max(300, height))}px`;
    };
    bridge.onerror = error => log("bridge-error", { message: error.message });
    const initialized = new Promise<void>(resolve => { bridge!.oninitialized = () => resolve(); });
    await bridge.connect(new PostMessageTransport(iframe.contentWindow!, iframe.contentWindow!));
    await bridge.sendSandboxResourceReady({ html: content.text, csp: ui.csp, permissions: ui.permissions });
    await timed(initialized, 45000, "MCP App initialization");
    log("app-initialized", { runId, sandboxOrigin: sandboxUrl.origin });
    await bridge.sendToolInput({ arguments: { run_id: runId } });
    status.textContent = "App initialized. Running initial Foundry model/tool turn…";
    const result = await api("tools/call", { name: tool.name, arguments: { run_id: runId } });
    await bridge.sendToolResult(result);
    status.textContent = `Initial source counter ${result.structuredContent?.counter}. Click Refresh inside the App.`;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    status.textContent = `Blocked: ${message}`;
    log("blocked", { message });
  } finally {
    button.disabled = false;
  }
};
