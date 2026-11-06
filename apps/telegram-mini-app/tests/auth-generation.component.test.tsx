import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useState } from "react";
import { AuthProvider, useAuth } from "@/components/auth-provider";
import { AuthApiError } from "@/lib/auth";

const id = "00000000-0000-4000-8000-000000000001";
const profile = {
  id,
  telegram_id: 123456789,
  username: null,
  full_name: "Анна",
  role: "CLIENT",
  created_at: "2026-11-04T08:00:00Z",
};
let resolveOperation: ((value: string) => void) | undefined;
function Probe() {
  const auth = useAuth(),
    [result, setResult] = useState("");
  return (
    <>
      <p>{auth.status}</p>
      <p>{auth.credentials?.user.full_name}</p>
      <p>{result}</p>
      <button
        onClick={() =>
          void auth
            .withAccount(
              id,
              () =>
                new Promise<string>((resolve) => {
                  resolveOperation = resolve;
                }),
            )
            .then(
              () => setResult("Operation completed"),
              () => setResult("Operation discarded"),
            )
        }
      >
        Start operation
      </button>
      <button onClick={() => void auth.saveFullName("Анна Новая")}>
        Update profile
      </button>
      <button onClick={() => void auth.signOut()}>Log out</button>
    </>
  );
}
beforeEach(() => {
  sessionStorage.clear();
  resolveOperation = undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      if (path.endsWith("/auth/session"))
        return Response.json({
          access_token: "synthetic-token",
          token_type: "bearer",
          expires_in: 900,
          user: profile,
        });
      if (path.endsWith("/auth/logout"))
        return new Response(null, { status: 204 });
      if (path.endsWith("/me") && init.method === "PATCH")
        return Response.json({ ...profile, full_name: "Анна Новая" });
      throw new AuthApiError("Unexpected request", 503);
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
test("same-account profile update does not discard an in-flight order operation", async () => {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await screen.findByText("authenticated");
  await userEvent.click(screen.getByText("Start operation"));
  await waitFor(() => expect(resolveOperation).toBeDefined());
  await userEvent.click(screen.getByText("Update profile"));
  await screen.findByText("Анна Новая");
  await act(async () => resolveOperation!("done"));
  await screen.findByText("Operation completed");
});
test("logout discards an operation that finishes after the auth boundary changed", async () => {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await screen.findByText("authenticated");
  await userEvent.click(screen.getByText("Start operation"));
  await waitFor(() => expect(resolveOperation).toBeDefined());
  await userEvent.click(screen.getByText("Log out"));
  await screen.findByText("anonymous");
  await act(async () => resolveOperation!("old result"));
  await screen.findByText("Operation discarded");
});
