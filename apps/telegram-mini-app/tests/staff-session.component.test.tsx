import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StaffHome from "../../kitchen-app/src/app/page";

vi.mock("../../kitchen-app/src/components/admin-panel", () => ({
  AdminPanel: () => null,
}));
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const order = (number: string) => ({
  id: "10000000-0000-4000-8000-000000000001",
  order_number: number,
  user_id: "20000000-0000-4000-8000-000000000001",
  slot_id: "30000000-0000-4000-8000-000000000001",
  slot_start_time: new Date(Date.now() + 3_600_000).toISOString(),
  slot_end_time: new Date(Date.now() + 4_200_000).toISOString(),
  status: "PENDING",
  total_amount: 14500,
  version: 1,
  payment_status: "DEMO_PAID",
  items: [],
});
const page = (number: string) => ({
  items: [order(number)],
  total: 1,
  limit: 100,
  offset: 0,
});
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

test("overlapping staff actions submit one versioned mutation", async () => {
  let complete!: (value: Response) => void;
  const pending = new Promise<Response>(resolve => { complete = resolve; });
  let mutations = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    if (url.endsWith("/users/auth/staff")) return response({
      access_token: "COOK", expires_in: 900,
      user: {id: "COOK", role: "COOK", full_name: "COOK"},
    });
    if (init.method === "PATCH") { mutations += 1; return pending; }
    return response(page("MAI-200002"));
  }));
  const user = userEvent.setup();
  render(<StaffHome />);
  await screen.findByRole("button", {name: "Войти"});
  await user.type(screen.getByLabelText("Логин"), "cook");
  await user.type(screen.getByLabelText("Пароль"), "synthetic-password");
  await user.click(screen.getByRole("button", {name: "Войти"}));
  const button = await screen.findByRole("button", {name: "Начать приготовление"});
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  expect(mutations).toBe(1);
  await act(async () => { complete(response(order("MAI-200002"))); await pending; });
});

test.each(["success", "unauthorized"])(
  "late admin queue %s cannot affect a new cook session",
  async (outcome) => {
    let completeAdmin!: (value: Response) => void;
    const delayedAdmin = new Promise<Response>((resolve) => {
      completeAdmin = resolve;
    });
    let adminQueueStarted = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        if (url.endsWith("/users/auth/staff")) {
          const role =
            JSON.parse(init.body as string).username === "admin"
              ? "ADMIN"
              : "COOK";
          return response({
            access_token: role,
            expires_in: 900,
            user: { id: role, role, full_name: role },
          });
        }
        if (url.includes("/orders/")) {
          if (
            new Headers(init.headers).get("Authorization") === "Bearer ADMIN"
          ) {
            adminQueueStarted = true;
            return delayedAdmin;
          }
          return response(page("MAI-200002"));
        }
        throw new Error("Unexpected request");
      }),
    );
    const user = userEvent.setup();
    render(<StaffHome />);
    await screen.findByRole("button", { name: "Войти" });
    await user.type(screen.getByLabelText("Логин"), "admin");
    await user.type(screen.getByLabelText("Пароль"), "synthetic-password");
    await user.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(adminQueueStarted).toBe(true));
    await user.click(screen.getByRole("button", { name: "Выйти" }));
    await user.type(screen.getByLabelText("Логин"), "cook");
    await user.type(screen.getByLabelText("Пароль"), "synthetic-password");
    await user.click(screen.getByRole("button", { name: "Войти" }));
    await screen.findByRole("heading", { name: "MAI-200002" });
    await act(async () => {
      completeAdmin(
        outcome === "success"
          ? response(page("MAI-100001"))
          : response({ detail: "Expired" }, 401),
      );
      await delayedAdmin;
    });
    expect(screen.getByRole("heading", { name: "MAI-200002" })).toBeTruthy();
    expect(screen.queryByText("MAI-100001")).toBeNull();
    expect(screen.queryByRole("button", { name: "Войти" })).toBeNull();
  },
);
