import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useState } from "react";
import { CheckoutPanel, OrdersPanel } from "@/components/order-workspace";
import {
  JOURNAL_KEY,
  createIntent,
  persistIntent,
  readIntent,
} from "@/lib/checkout";

const state = vi.hoisted(() => ({
  userId: "00000000-0000-4000-8000-000000000001",
}));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({
    status: "authenticated",
    credentials: { user: { id: state.userId, role: "CLIENT" } },
    busy: false,
    withAccount: async (
      id: string,
      operation: (token: string) => Promise<unknown>,
    ) => {
      if (id !== state.userId) throw new Error("Account changed");
      return operation(id);
    },
  }),
}));
const accountA = "00000000-0000-4000-8000-000000000001",
  accountB = "00000000-0000-4000-8000-000000000002",
  dish = "10000000-0000-4000-8000-000000000001",
  slot = "20000000-0000-4000-8000-000000000001";
let client: QueryClient,
  mode: string,
  postCalls: { key: string; body: string }[],
  orders: Record<string, Record<string, unknown>>,
  original: Map<string, Record<string, unknown>>,
  hold: ((value: Response) => void) | undefined;
const complete = vi.fn();
function fixture(body: Record<string, unknown>, owner = state.userId) {
  return {
    id: crypto.randomUUID(),
    user_id: owner,
    order_number: "MAI-000001",
    slot_id: body.slot_id,
    slot_start_time: "2099-11-04T09:00:00Z",
    slot_end_time: "2099-11-04T09:30:00Z",
    status: "PENDING",
    version: 1,
    total_amount: body.expected_total_amount,
    created_at: "2026-11-04T09:00:00Z",
    updated_at: "2026-11-04T09:00:00Z",
    items: [
      {
        id: crypto.randomUUID(),
        menu_item_id: dish,
        quantity: 1,
        price_at_moment: body.expected_total_amount,
        name_at_moment: "Суп",
      },
    ],
  };
}
function Harness() {
  const [cart, setCart] = useState([{ id: dish, quantity: 1 }]);
  return (
    <QueryClientProvider client={client}>
      <CheckoutPanel
        cart={cart}
        total={cart.length ? 14500 : 0}
        onComplete={(intent) => {
          complete(intent);
          setCart([]);
        }}
      />
      <OrdersPanel />
    </QueryClientProvider>
  );
}
beforeEach(() => {
  sessionStorage.clear();
  state.userId = accountA;
  mode = "normal";
  orders = {};
  original = new Map();
  postCalls = [];
  hold = undefined;
  complete.mockReset();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options: RequestInit = {}) => {
      const method = options.method ?? "GET",
        token = (
          options.headers as Record<string, string>
        ).Authorization.replace("Bearer ", "");
      if (path.startsWith("/api/v1/orders/slots"))
        return Response.json([
          {
            id: slot,
            start_time: "2099-11-04T09:00:00Z",
            end_time: "2099-11-04T09:30:00Z",
            capacity: 5,
            current_orders: 0,
            remaining_capacity: 5,
          },
        ]);
      if (path === "/api/v1/orders/" && method === "POST") {
        const key = (options.headers as Record<string, string>)[
            "Idempotency-Key"
          ],
          body = String(options.body);
        postCalls.push({ key, body });
        if (mode === "price" || mode === "recovery-price")
          return Response.json(
            {
              detail: {
                code: "PRICE_CHANGED",
                message: "Confirm",
                total_amount: 15500,
              },
            },
            { status: 409 },
          );
        let order = original.get(key);
        if (!order) {
          order = fixture(JSON.parse(body), token);
          original.set(key, structuredClone(order));
          orders[String(order.id)] = order;
        }
        if (mode === "held")
          return new Promise<Response>((resolve) => {
            hold = resolve;
          });
        if (mode === "lost") {
          mode = "normal";
          throw new TypeError("Lost ACK after commit");
        }
        return Response.json(order, { status: 201 });
      }
      if (path.includes("/cancel")) {
        const id = path.split("/").at(-2)!,
          order = orders[id];
        if (mode === "version-conflict") {
          orders[id] = { ...order, status: "PREPARING", version: 2 };
          return Response.json(
            { detail: { code: "VERSION_CONFLICT", message: "Refresh" } },
            { status: 409 },
          );
        }
        orders[id] = { ...order, status: "CANCELLED", version: 2 };
        return Response.json(orders[id]);
      }
      if (path.includes("?limit=10")) {
        const items = Object.values(orders).filter((o) => o.user_id === token);
        return Response.json({
          items,
          total: items.length,
          limit: 10,
          offset: 0,
        });
      }
      const id = path.split("/").at(-1)!;
      return orders[id]
        ? Response.json(orders[id])
        : Response.json({ detail: "Not found" }, { status: 404 });
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function selectSlot() {
  await screen.findByRole("option", { name: /МСК · мест/ });
  await userEvent.selectOptions(
    await screen.findByLabelText("Когда заберёте обед · МСК"),
    slot,
  );
}
async function submit() {
  await selectSlot();
  await userEvent.click(
    screen.getByRole("button", { name: /Заказать за 145/ }),
  );
}

test("unknown ACK survives remount and resolves the original intent with current REST state", async () => {
  mode = "lost";
  const first = render(<Harness />);
  await submit();
  await screen.findByRole("button", { name: "Восстановить исходный заказ" });
  const saved = sessionStorage.getItem(JOURNAL_KEY);
  expect(saved).not.toBeNull();
  const row = Object.values(orders)[0];
  orders[String(row.id)] = { ...row, status: "PREPARING", version: 2 };
  first.unmount();
  render(<Harness />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Восстановить исходный заказ" }),
  );
  await waitFor(() => expect(sessionStorage.getItem(JOURNAL_KEY)).toBeNull());
  expect(postCalls).toHaveLength(2);
  expect(postCalls[0]).toEqual(postCalls[1]);
  expect(complete).toHaveBeenCalledTimes(1);
  expect(
    (await screen.findByRole("article", { name: "Талон заказа" })).textContent,
  ).toContain("Готовится");
  expect(screen.queryByRole("button", { name: "Отменить заказ" })).toBeNull();
});
test("fresh changed-price rejection needs a separate explicit confirmation and fresh key", async () => {
  mode = "price";
  render(<Harness />);
  await submit();
  await screen.findByRole("button", { name: /Подтвердить новую сумму 155/ });
  expect(postCalls).toHaveLength(1);
  expect(readIntent(sessionStorage)).toBeNull();
  mode = "normal";
  await userEvent.dblClick(
    screen.getByRole("button", { name: /Подтвердить новую сумму 155/ }),
  );
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  expect(postCalls).toHaveLength(2);
  expect(postCalls[0].key).not.toBe(postCalls[1].key);
  expect(JSON.parse(postCalls[1].body).expected_total_amount).toBe(15500);
});
test("a price rejection during uncertain recovery never permits silently replacing the old body", async () => {
  persistIntent(
    sessionStorage,
    createIntent(accountA, [{ id: dish, quantity: 1 }], slot, 14500),
  );
  const raw = sessionStorage.getItem(JOURNAL_KEY);
  mode = "recovery-price";
  render(<Harness />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Восстановить исходный заказ" }),
  );
  await waitFor(() => expect(postCalls).toHaveLength(1));
  expect(sessionStorage.getItem(JOURNAL_KEY)).toBe(raw);
  expect(
    screen.queryByRole("button", { name: /Подтвердить новую сумму/ }),
  ).toBeNull();
});
test("foreign account sees no old request amount or retry and late success cannot clear it", async () => {
  mode = "held";
  const view = render(<Harness />);
  await submit();
  await waitFor(() => expect(hold).toBeDefined());
  const raw = sessionStorage.getItem(JOURNAL_KEY);
  state.userId = accountB;
  view.rerender(<Harness />);
  await screen.findByText("Есть запрос другого аккаунта");
  expect(
    screen.queryByRole("button", { name: "Восстановить исходный заказ" }),
  ).toBeNull();
  await act(async () =>
    hold!(Response.json(Object.values(orders)[0], { status: 201 })),
  );
  expect(sessionStorage.getItem(JOURNAL_KEY)).toBe(raw);
  expect(complete).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /MAI-000001/ })).toBeNull();
});
test("clearing a corrupted intent requires a visible loss warning and an explicit second action", async () => {
  sessionStorage.setItem(JOURNAL_KEY, "broken");
  render(<Harness />);
  await userEvent.click(
    await screen.findByRole("button", {
      name: "Очистить данные с предупреждением",
    }),
  );
  const warning = await screen.findByRole("alertdialog", {
    name: "Предупреждение об очистке запроса",
  });
  expect(warning.textContent).toContain("может создать ещё один заказ");
  expect(sessionStorage.getItem(JOURNAL_KEY)).toBe("broken");
  await userEvent.click(
    screen.getByRole("button", { name: "Вернуться к запросу" }),
  );
  expect(sessionStorage.getItem(JOURNAL_KEY)).toBe("broken");
  await userEvent.click(
    screen.getByRole("button", { name: "Очистить данные с предупреждением" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить ключ восстановления" }),
  );
  expect(sessionStorage.getItem(JOURNAL_KEY)).toBeNull();
  expect(postCalls).toHaveLength(0);
});
test("unwritable storage blocks POST before any request is sent", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Quota");
  });
  render(<Harness />);
  await submit();
  await screen.findByText(/Заказ не отправлен/);
  expect(postCalls).toHaveLength(0);
});
test("cancellation needs inline confirmation; version conflict refreshes to preparing", async () => {
  render(<Harness />);
  await submit();
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  await screen.findByRole("article", { name: "Талон заказа" });
  mode = "version-conflict";
  await userEvent.click(screen.getByRole("button", { name: "Отменить заказ" }));
  expect(orders[Object.keys(orders)[0]].status).toBe("PENDING");
  await userEvent.click(
    await screen.findByRole("button", { name: "Сохранить заказ" }),
  );
  expect(orders[Object.keys(orders)[0]].status).toBe("PENDING");
  await userEvent.click(screen.getByRole("button", { name: "Отменить заказ" }));
  await userEvent.click(
    screen.getByRole("button", { name: "Да, отменить заказ" }),
  );
  await waitFor(() =>
    expect(orders[Object.keys(orders)[0]].status).toBe("PREPARING"),
  );
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Отменить заказ" })).toBeNull(),
  );
  expect(
    screen.getByRole("article", { name: "Талон заказа" }).textContent,
  ).toContain("Готовится");
});

test("known created order remains visible when local journal cleanup fails", async () => {
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  render(<Harness />);
  await submit();
  await screen.findByText(
    /Заказ подтверждён, но ключ восстановления не удалось удалить/,
  );
  expect(postCalls).toHaveLength(1);
  expect(complete).not.toHaveBeenCalled();
  expect(readIntent(sessionStorage)).not.toBeNull();
  await screen.findByRole("article", { name: "Талон заказа" });
  expect(screen.queryByRole("button", { name: /Заказать за/ })).toBeNull();
});
