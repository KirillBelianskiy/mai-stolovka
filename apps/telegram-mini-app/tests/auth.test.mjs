import assert from "node:assert/strict";
import test from "node:test";
import {
  AuthApiError,
  loginTelegram,
  loadProfile,
  logout,
  restoreOrLogin,
  restoreSession,
  switchTelegramAccount,
  updateProfile,
  withTokenRefresh,
} from "../src/lib/auth.ts";

const profile = {
  id: "6c375712-23bc-4aa4-85d2-1950608520f0",
  telegram_id: 123456789,
  username: "misha",
  full_name: "Миша",
  role: "CLIENT",
  created_at: "2026-11-04T10:00:00Z",
};
const credentials = {
  access_token: "signed-access-token",
  token_type: "bearer",
  expires_in: 900,
  user: profile,
};

test("restores the browser session before attempting Telegram login", async () => {
  const calls = [];
  const result = await restoreOrLogin("auth_date=1&hash=signed", async (url, options) => {
    calls.push({ url, options });
    return calls.length === 1
      ? Response.json(credentials, { status: 401 })
      : Response.json(credentials);
  });

  assert.deepEqual(result, credentials);
  assert.deepEqual(calls.map(({ url }) => url), [
    "/api/v1/users/auth/session",
    "/api/v1/users/auth/telegram",
  ]);
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(calls[1].options.body, JSON.stringify({ init_data: "auth_date=1&hash=signed" }));
});

test("does not retry Telegram login when the cookie restore fails for another reason", async () => {
  const calls = [];
  await assert.rejects(
    restoreOrLogin("fresh-init-data", async (url) => {
      calls.push(url);
      return Response.json({ detail: "Unavailable" }, { status: 503 });
    }),
    (error) => error instanceof AuthApiError && error.status === 503,
  );
  assert.deepEqual(calls, ["/api/v1/users/auth/session"]);
});

test("restore without fresh Telegram data reports unauthorized without a fake login", async () => {
  const calls = [];
  await assert.rejects(
    restoreOrLogin(undefined, async (url) => {
      calls.push(url);
      return Response.json({ detail: "Unauthorized" }, { status: 401 });
    }),
    (error) => error instanceof AuthApiError && error.status === 401,
  );
  assert.deepEqual(calls, ["/api/v1/users/auth/session"]);
});

test("rejects malformed login and restore responses", async () => {
  await assert.rejects(
    restoreSession(async () => Response.json({ ...credentials, access_token: "" })),
    /Invalid login response/,
  );
  await assert.rejects(
    loginTelegram("raw-init-data", async () =>
      Response.json({ ...credentials, user: { ...profile, role: "UNKNOWN" } }),
    ),
    /Invalid login response/,
  );
});

test("explicit account switch verifies raw Telegram data and returns the new session", async () => {
  let call;
  const switched = { ...credentials, user: { ...profile, id: "5fcf4b63-f7c2-45ec-a73e-2c416a53b477" } };
  const result = await switchTelegramAccount(credentials, "raw-account-b-init-data", async (url, options) => {
    call = { url, options };
    return Response.json(switched);
  });

  assert.equal(result.ok, true);
  assert.deepEqual(result.credentials, switched);
  assert.equal(call.url, "/api/v1/users/auth/telegram");
  assert.equal(call.options.body, JSON.stringify({ init_data: "raw-account-b-init-data" }));
  assert.equal(call.options.credentials, "same-origin");
});

test("a failed account switch keeps the current in-memory session", async () => {
  const result = await switchTelegramAccount(credentials, "invalid-account-data", async () =>
    Response.json({ detail: "Unauthorized" }, { status: 401 }),
  );

  assert.equal(result.ok, false);
  assert.equal(result.credentials, credentials);
  assert.ok(result.error instanceof AuthApiError);
  assert.equal(result.error.status, 401);
});

test("profile reads and updates use the in-memory bearer token and same-origin requests", async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    return Response.json(url.endsWith("/me") && options.method === "PATCH"
      ? { ...profile, full_name: "Михаил" }
      : profile);
  };

  assert.deepEqual(await loadProfile(credentials.access_token, fetcher), profile);
  assert.equal(
    (await updateProfile(credentials.access_token, "Михаил", fetcher)).full_name,
    "Михаил",
  );
  assert.deepEqual(calls.map(({ options }) => options.credentials), [
    "same-origin",
    "same-origin",
  ]);
  assert.deepEqual(calls.map(({ options }) => options.headers.Authorization), [
    "Bearer signed-access-token",
    "Bearer signed-access-token",
  ]);
  assert.equal(calls[1].options.body, JSON.stringify({ full_name: "Михаил" }));
});

test("logout revokes the cookie session through a same-origin POST", async () => {
  let call;
  await logout(async (url, options) => {
    call = { url, options };
    return new Response(null, { status: 204 });
  });
  assert.equal(call.url, "/api/v1/users/auth/logout");
  assert.equal(call.options.method, "POST");
  assert.equal(call.options.credentials, "same-origin");
  assert.equal(call.options.headers?.Authorization, undefined);
});

test("network errors are not converted into anonymous success", async () => {
  await assert.rejects(
    restoreSession(async () => {
      throw new TypeError("Network unavailable");
    }),
    /Network unavailable/,
  );
});

test("an expired access token restores once and retries the authorized request", async () => {
  const tokens = [];
  const refreshed = { ...credentials, access_token: "fresh-access-token" };
  const result = await withTokenRefresh(
    "expired-access-token",
    async (token) => {
      tokens.push(token);
      if (token === "expired-access-token") {
        throw new AuthApiError("Expired", 401);
      }
      return profile;
    },
    async () => refreshed,
    profile.id,
  );
  assert.deepEqual(tokens, ["expired-access-token", "fresh-access-token"]);
  assert.deepEqual(result, { value: profile, credentials: refreshed });
});

test("failed access-token refresh does not retry the protected request", async () => {
  let attempts = 0;
  await assert.rejects(
    withTokenRefresh(
      "expired-access-token",
      async () => {
        attempts += 1;
        throw new AuthApiError("Expired", 401);
      },
      async () => {
        throw new AuthApiError("Session expired", 401);
      },
      profile.id,
    ),
    (error) => error instanceof AuthApiError && error.status === 401,
  );
  assert.equal(attempts, 1);
});

test("name updates reject blank and overlong values before sending a request", async () => {
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    return Response.json(profile);
  };
  await assert.rejects(updateProfile(credentials.access_token, "   ", fetcher));
  await assert.rejects(updateProfile(credentials.access_token, "x".repeat(257), fetcher));
  assert.equal(calls, 0);
});

test("account change during token restoration never retries the old account operation", async () => {
  let attempts = 0;
  const other = {
    ...credentials,
    user: { ...profile, id: "7c375712-23bc-4aa4-85d2-1950608520f0" },
  };
  await assert.rejects(
    withTokenRefresh(
      credentials.access_token,
      async () => {
        attempts += 1;
        if (attempts === 1) throw new AuthApiError("Expired", 401);
        return "wrong account mutation";
      },
      async () => other,
      profile.id,
    ),
    (error) => error instanceof AuthApiError && error.status === 409,
  );
  assert.equal(attempts, 1);
});

test("raw Telegram data is read from launch URLs without a storage cache", async () => {
  const { readTelegramInitData } = await import("../src/lib/auth.ts");
  const raw = "auth_date=1&user=%7B%22id%22%3A7%7D&hash=signed";
  const launch = `https://example.test/#tgWebAppData=${encodeURIComponent(raw)}&tgWebAppVersion=8.0`;
  assert.equal(readTelegramInitData(launch), raw);
  assert.equal(readTelegramInitData("https://example.test/", launch), raw);
  assert.equal(readTelegramInitData("https://example.test/?tgWebAppData=" + encodeURIComponent(raw)), raw);
  assert.equal(readTelegramInitData("https://example.test/"), undefined);
  assert.equal(readTelegramInitData("not a URL"), undefined);
});
