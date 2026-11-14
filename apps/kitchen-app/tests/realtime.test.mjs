import assert from "node:assert/strict";
import { test } from "node:test";

test("a hint during REST fetch triggers a second filtered membership fetch", async () => {
  const { createQueueRefresh } = await import("../src/lib/realtime.ts");
  let release;
  const firstResponse = new Promise((resolve) => { release = resolve; });
  let fetches = 0;
  let visible = [];
  const refresh = createQueueRefresh(async () => {
    visible = ++fetches === 1 ? await firstResponse : ["newly READY"];
  });
  const initial = refresh.request();
  await Promise.resolve();
  assert.equal(fetches, 1);
  refresh.request(true);
  refresh.request(true);
  release(["no longer READY"]);
  await initial;
  assert.equal(fetches, 2);
  assert.deepEqual(visible, ["newly READY"]);
});

test("versions coalesce duplicate and out-of-order hints, including after gaps", async () => {
  const { createHintTracker } = await import("../src/lib/realtime.ts");
  const accept = createHintTracker();
  const id = "9db26a8c-b2e3-4520-b8b4-0769f507aaaa";
  const hint = (version) => ({ type: "order.changed", order_id: id, version });
  assert.equal(accept(hint(2)), true);
  assert.equal(accept(hint(2)), false);
  assert.equal(accept(hint(7)), true);
  assert.equal(accept(hint(4)), false);
  assert.equal(accept(hint(7.1)), false);
  assert.equal(accept({ ...hint(8), order_id: "invalid" }), false);
});

test("subscribe before REST, reconcile after loss and rejoin, and stop on expiry", async (t) => {
  const { startKitchenRealtime } = await import("../src/lib/realtime.ts");
  const timers = new Map();
  const sockets = [];
  let timerId = 0;

  class Socket {
    constructor(url) {
      this.url = url.href;
      sockets.push(this);
    }

    open() { this.onopen(); }
    send(frame) { this.auth = JSON.parse(frame); }
    message(body) { this.onmessage({ data: JSON.stringify(body) }); }
    disconnect(code) { this.onclose({ code }); }
    close() { this.closed = true; }
  }

  const window = new EventTarget();
  const document = new EventTarget();
  window.location = { href: "https://kitchen.example/" };
  document.visibilityState = "visible";
  window.setTimeout = (callback, delay) => {
    const id = ++timerId;
    timers.set(id, { callback, delay });
    return id;
  };
  window.clearTimeout = (id) => timers.delete(id);
  window.setInterval = window.setTimeout;
  window.clearInterval = window.clearTimeout;
  t.mock.method(Math, "random", () => 0);
  t.mock.property(globalThis, "WebSocket", Socket);
  globalThis.window = window;
  globalThis.document = document;

  const refreshes = [];
  const unauthorized = [];
  const stop = startKitchenRealtime({
    token: "staff-token",
    refresh: (quiet) => refreshes.push(quiet),
    onUnauthorized: (code) => unauthorized.push(code),
  });
  t.after(() => {
    stop();
    delete globalThis.window;
    delete globalThis.document;
  });

  const first = sockets[0];
  assert.equal(first.url, "wss://kitchen.example/api/v1/ws/kitchen");
  first.open();
  assert.deepEqual(first.auth, { type: "auth", access_token: "staff-token" });
  const hint = {
    type: "order.changed",
    order_id: "9db26a8c-b2e3-4520-b8b4-0769f507aaaa",
    version: 5,
  };
  first.message(hint);
  assert.deepEqual(refreshes, []);
  first.message({ type: "ready" });
  first.message(hint);
  first.message(hint);
  assert.deepEqual(refreshes, [false, true]);
  first.disconnect(1013);
  assert.deepEqual(refreshes, [false, true, true]);
  assert.ok([...timers.values()].some(({ delay }) => delay === 750));

  window.dispatchEvent(new Event("online"));
  assert.equal(sockets.length, 2);
  assert.equal(refreshes.length, 4);
  const second = sockets[1];
  second.open();
  first.message({ ...hint, version: 6 });
  assert.equal(refreshes.length, 4);
  second.message({ type: "ready" });
  assert.equal(refreshes.length, 5);
  window.dispatchEvent(new Event("focus"));
  assert.equal(refreshes.length, 6);
  second.disconnect(4401);
  window.dispatchEvent(new Event("online"));
  assert.deepEqual(unauthorized, [4401]);
  assert.equal(timers.size, 0);
  assert.equal(sockets.length, 2);
});
