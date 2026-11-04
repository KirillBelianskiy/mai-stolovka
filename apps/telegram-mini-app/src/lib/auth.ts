export type UserProfile = {
  id: string;
  telegram_id: number | null;
  username: string | null;
  full_name: string;
  role: "CLIENT" | "COOK" | "CASHIER" | "ADMIN";
  created_at: string;
};

export type AuthCredentials = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserProfile;
};

export class AuthApiError extends Error {
  readonly status: number | null;

  constructor(
    message: string,
    status: number | null,
  ) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
  }
}

type Fetcher = typeof fetch;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Invalid user profile");
  }
  return value as Record<string, unknown>;
}

function decodeProfile(value: unknown): UserProfile {
  const row = record(value);
  const roles = ["CLIENT", "COOK", "CASHIER", "ADMIN"] as const;
  if (
    typeof row.id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      row.id,
    ) ||
    (row.telegram_id !== null &&
      (typeof row.telegram_id !== "number" ||
        !Number.isInteger(row.telegram_id) ||
        row.telegram_id < 1)) ||
    (row.username !== null && typeof row.username !== "string") ||
    typeof row.full_name !== "string" ||
    row.full_name.trim().length === 0 ||
    row.full_name.length > 256 ||
    typeof row.role !== "string" ||
    !roles.includes(row.role as (typeof roles)[number]) ||
    typeof row.created_at !== "string" ||
    !Number.isFinite(Date.parse(row.created_at))
  ) {
    throw new Error("Invalid user profile");
  }
  return {
    id: row.id.toLowerCase(),
    telegram_id: row.telegram_id,
    username: row.username,
    full_name: row.full_name,
    role: row.role as UserProfile["role"],
    created_at: row.created_at,
  };
}

function decodeCredentials(value: unknown): AuthCredentials {
  try {
    const row = record(value);
    if (
      typeof row.access_token !== "string" ||
      row.access_token.length === 0 ||
      row.access_token.length > 32768 ||
      row.token_type !== "bearer" ||
      typeof row.expires_in !== "number" ||
      !Number.isInteger(row.expires_in) ||
      row.expires_in < 1 ||
      row.expires_in > 900
    ) {
      throw new Error("Invalid credentials");
    }
    return {
      access_token: row.access_token,
      token_type: "bearer",
      expires_in: row.expires_in,
      user: decodeProfile(row.user),
    };
  } catch {
    throw new Error("Invalid login response");
  }
}

async function request(
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<Response> {
  return fetcher(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
}

async function requestJson(
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<unknown> {
  const response = await request(path, init, fetcher);
  if (!response.ok) {
    throw new AuthApiError(`User Service request failed (${response.status})`, response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new Error("Invalid User Service response");
  }
}

export async function restoreSession(
  fetcher: Fetcher = fetch,
): Promise<AuthCredentials> {
  return decodeCredentials(
    await requestJson(
      "/api/v1/users/auth/session",
      { method: "POST" },
      fetcher,
    ),
  );
}

export async function loginTelegram(
  initData: string,
  fetcher: Fetcher = fetch,
): Promise<AuthCredentials> {
  if (initData.length === 0 || initData.length > 16384) {
    throw new Error("Invalid Telegram initData");
  }
  return decodeCredentials(
    await requestJson(
      "/api/v1/users/auth/telegram",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData }),
      },
      fetcher,
    ),
  );
}

export type AccountSwitchResult =
  | { ok: true; credentials: AuthCredentials }
  | { ok: false; credentials: AuthCredentials; error: unknown };

export async function switchTelegramAccount(
  current: AuthCredentials,
  initData: string,
  fetcher: Fetcher = fetch,
): Promise<AccountSwitchResult> {
  try {
    return { ok: true, credentials: await loginTelegram(initData, fetcher) };
  } catch (error) {
    return { ok: false, credentials: current, error };
  }
}

export async function restoreOrLogin(
  initData: string | undefined,
  fetcher: Fetcher = fetch,
): Promise<AuthCredentials> {
  try {
    return await restoreSession(fetcher);
  } catch (error) {
    if (
      !(error instanceof AuthApiError) ||
      error.status !== 401 ||
      !initData
    ) {
      throw error;
    }
    return loginTelegram(initData, fetcher);
  }
}

export async function withTokenRefresh<T>(
  accessToken: string,
  operation: (token: string) => Promise<T>,
  restore: () => Promise<AuthCredentials> = restoreSession,
): Promise<{ value: T; credentials: AuthCredentials | null }> {
  try {
    return { value: await operation(accessToken), credentials: null };
  } catch (error) {
    if (!(error instanceof AuthApiError) || error.status !== 401) throw error;
    const refreshed = await restore();
    return {
      value: await operation(refreshed.access_token),
      credentials: refreshed,
    };
  }
}

export async function loadProfile(
  accessToken: string,
  fetcher: Fetcher = fetch,
): Promise<UserProfile> {
  return decodeProfile(
    await requestJson(
      "/api/v1/users/me",
      { method: "GET", headers: { Authorization: `Bearer ${accessToken}` } },
      fetcher,
    ),
  );
}

export async function updateProfile(
  accessToken: string,
  fullName: string,
  fetcher: Fetcher = fetch,
): Promise<UserProfile> {
  const normalized = fullName.trim();
  if (normalized.length === 0 || normalized.length > 256) {
    throw new Error("Name must contain 1–256 characters");
  }
  return decodeProfile(
    await requestJson(
      "/api/v1/users/me",
      {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ full_name: normalized }),
      },
      fetcher,
    ),
  );
}

export async function logout(fetcher: Fetcher = fetch): Promise<void> {
  const response = await request(
    "/api/v1/users/auth/logout",
    { method: "POST" },
    fetcher,
  );
  if (!response.ok) {
    throw new AuthApiError(
      `User Service logout failed (${response.status})`,
      response.status,
    );
  }
}
