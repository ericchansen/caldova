import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const code = ts.transpileModule(
  readFileSync(new URL("./src/sandbox-readiness.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText;

function fixture() {
  let clock = 0;
  let nextId = 0;
  const listeners = new Set();
  const timers = new Map();
  const exports = {};
  const iframe = {
    contentWindow: {},
    set src(value) {
      assert.equal(listeners.size, 1, "listener must be registered before navigation");
      this.lastSrc = value;
    },
  };
  runInNewContext(code, {
    exports,
    location: { origin: "https://tab.example.invalid" },
    window: {
      addEventListener: (type, callback) => { assert.equal(type, "message"); listeners.add(callback); },
      removeEventListener: (type, callback) => { assert.equal(type, "message"); listeners.delete(callback); },
    },
    setTimeout: (callback, delay) => {
      const id = ++nextId;
      timers.set(id, { at: clock + delay, callback });
      return id;
    },
    clearTimeout: id => timers.delete(id),
  });
  return {
    iframe, listeners, timers, exports,
    advance(ms) {
      clock += ms;
      for (const [id, timer] of timers) {
        if (timer.at <= clock) { timers.delete(id); timer.callback(); }
      }
    },
    message(overrides = {}) {
      const event = {
        source: iframe.contentWindow, origin: "https://sandbox.example.invalid",
        data: { method: "ui/notifications/sandbox-proxy-ready" }, ...overrides,
      };
      for (const listener of listeners) listener(event);
    },
    start() { return exports.loadSandboxProxy(iframe, new URL("https://sandbox.example.invalid/sandbox.html")); },
  };
}

test("official proxy-ready after 39-second document startup is accepted", async () => {
  const f = fixture();
  const ready = f.start();
  f.advance(39000); // Real retained Teams navigation took 38.879s before its first byte.
  assert.equal(f.listeners.size, 1);
  f.message();
  await ready;
  assert.equal(f.listeners.size, 0);
  assert.equal(f.timers.size, 0);
});

test("wrong source, origin or method cannot satisfy readiness", async () => {
  const f = fixture();
  const ready = f.start();
  f.message({ source: {} });
  f.message({ origin: "https://untrusted.example.invalid" });
  f.message({ origin: "null" });
  f.message({ data: { method: "load" } });
  assert.equal(f.listeners.size, 1);
  f.message();
  await ready;
});

test("missing handshake still fails at bounded 120 seconds and cleans listener", async () => {
  const f = fixture();
  const failed = assert.rejects(f.start(), /did not become ready within 120 seconds/);
  f.advance(119999);
  assert.equal(f.listeners.size, 1);
  f.advance(1);
  await failed;
  assert.equal(f.listeners.size, 0);
  assert.equal(f.timers.size, 0);
});

test("same-origin sandbox is rejected before navigation", () => {
  const f = fixture();
  assert.throws(() => f.exports.loadSandboxProxy(f.iframe, new URL("https://tab.example.invalid/sandbox.html")),
    /separate origin/);
  assert.equal(f.iframe.lastSrc, undefined);
});
