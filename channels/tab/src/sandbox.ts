// Official ext-apps basic-host double-frame pattern, with a fixed lab host allowlist.
// AppBridge owns the MCP Apps protocol; this file only relays the sandbox transport.
import type {
  McpUiSandboxProxyReadyNotification, McpUiSandboxResourceReadyNotification,
} from "@modelcontextprotocol/ext-apps/app-bridge";

// The sandbox server inserts its configured host origin into the HTML response.
// Never derive trust from a caller-controlled query string or referrer alone.
const expectedHost = document.querySelector<HTMLMetaElement>('meta[name="tab-host-origin"]')?.content;
if (!expectedHost || !expectedHost.startsWith("https://") || new URL(expectedHost).origin !== expectedHost) {
  throw new Error("Sandbox host origin is not configured.");
}
if (self === top || !document.referrer || new URL(document.referrer).origin !== expectedHost) {
  throw new Error("Sandbox requires the isolated tab host as its immediate parent.");
}
let isolated = false;
try { void window.parent.document; } catch { isolated = true; }
if (!isolated) throw new Error("Sandbox origin isolation failed.");
const inner = document.createElement("iframe");
inner.title = "Untrusted MCP App resource";
inner.style.cssText = "width:100%;height:100vh;border:0";
inner.setAttribute("sandbox", "allow-scripts allow-same-origin");
document.body.append(inner);
const resourceReady: McpUiSandboxResourceReadyNotification["method"] = "ui/notifications/sandbox-resource-ready";
const proxyReady: McpUiSandboxProxyReadyNotification["method"] = "ui/notifications/sandbox-proxy-ready";
let loaded = false;
window.addEventListener("message", event => {
  if (event.source === parent && event.origin === expectedHost) {
    if (event.data?.method === resourceReady) {
      if (loaded || typeof event.data.params?.html !== "string") return;
      loaded = true;
      // Keep the sandbox restriction fixed: source content cannot add navigation/popups.
      const doc = inner.contentDocument!;
      doc.open();
      doc.write(event.data.params.html);
      doc.close();
    } else {
      inner.contentWindow?.postMessage(event.data, location.origin);
    }
  } else if (event.source === inner.contentWindow && event.origin === location.origin) {
    parent.postMessage(event.data, expectedHost);
  }
});
parent.postMessage({ jsonrpc: "2.0", method: proxyReady, params: {} }, expectedHost);
