// Container Apps may scale to zero. The document can arrive after 30 seconds;
// readiness still requires the official notification, never just iframe.onload.
export const SANDBOX_READY_TIMEOUT_MS = 120000;

export function loadSandboxProxy(iframe: HTMLIFrameElement, url: URL): Promise<void> {
  if (url.origin === location.origin) throw new Error("Sandbox must have a separate origin.");
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", listener);
      reject(new Error("Sandbox proxy did not become ready within 120 seconds."));
    }, SANDBOX_READY_TIMEOUT_MS);
    const listener = (event: MessageEvent) => {
      if (event.source === iframe.contentWindow && event.origin === url.origin &&
          event.data?.method === "ui/notifications/sandbox-proxy-ready") {
        clearTimeout(timer);
        window.removeEventListener("message", listener);
        resolve();
      }
    };
    window.addEventListener("message", listener);
    // Register before navigation, including when a warm document responds immediately.
    iframe.src = url.href;
  });
}
