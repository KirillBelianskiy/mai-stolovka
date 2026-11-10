import assert from "node:assert/strict";
import test from "node:test";
import { onRequest } from "../functions/api/v1/[[path]].ts";

test("Pages API proxy pins the backend and preserves session headers and Set-Cookie", async () => {
  const originalFetch = globalThis.fetch;
  let forwarded;
  globalThis.fetch = async (request) => {
    forwarded = request;
    return new Response("ok", { headers: { "Set-Cookie": "mai_session=test; Path=/api/v1/users/auth; Secure; HttpOnly" } });
  };

  try {
    const request = new Request("https://attacker.example/api/v1/users/auth/session?check=1", {
      headers: {
        Authorization: "Bearer test-fixture",
        Cookie: "mai_session=test",
        Origin: "https://preview.example.pages.dev",
      },
    });
    const response = await onRequest({ request });

    assert.equal(forwarded.url, "https://api-test.maistolovka.me/api/v1/users/auth/session?check=1");
    assert.equal(forwarded.headers.get("Authorization"), "Bearer test-fixture");
    assert.equal(forwarded.headers.get("Cookie"), "mai_session=test");
    assert.equal(forwarded.headers.get("Origin"), "https://preview.example.pages.dev");
    assert.match(response.headers.get("Set-Cookie"), /mai_session=test/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Pages API proxy carries a WebSocket upgrade to the fixed backend", async () => {
  const originalFetch = globalThis.fetch;
  let forwarded;
  globalThis.fetch = async (request) => {
    forwarded = request;
    return new Response(null, { status: 200 });
  };

  try {
    const request = new Request("https://preview.example.pages.dev/api/v1/ws/kitchen", {
      headers: {
        Connection: "Upgrade",
        Origin: "https://preview.example.pages.dev",
        Upgrade: "websocket",
      },
    });
    await onRequest({ request });

    assert.equal(forwarded.url, "https://api-test.maistolovka.me/api/v1/ws/kitchen");
    assert.equal(forwarded.headers.get("Upgrade"), "websocket");
    assert.equal(forwarded.headers.get("Origin"), "https://preview.example.pages.dev");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
