import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/components/auth-provider";
import { MenuApp } from "@/components/menu-app";
import { CART_KEY } from "@/lib/menu";

vi.mock("@/components/order-workspace", () => ({
  CheckoutPanel: function CheckoutProbe({ onBack }: { onBack: () => void }) {
    const [pending, setPending] = useState(false);
    return (
      <section>
        <button onClick={onBack}>К корзине</button>
        <button onClick={() => setPending(true)}>
          {pending ? "Сохраняем исходный запрос" : "Начать проверку запроса"}
        </button>
      </section>
    );
  },
  OrdersPanel: () => <section>История аккаунта</section>,
}));
const category = { id: "00000000-0000-4000-8000-000000000001", name: "Супы", sort_order: 1 };
const dish = {
  id: "10000000-0000-4000-8000-000000000001",
  category_id: category.id,
  name: "Борщ",
  description: "Свекольный суп.",
  price: 15000,
  is_available: true,
  image_url: null,
};
const credentials = {
  access_token: "synthetic-token",
  token_type: "bearer",
  expires_in: 900,
  user: { id: "30000000-0000-4000-8000-000000000001", telegram_id: 123, username: "student",
    full_name: "Анна", role: "CLIENT", created_at: "2026-11-04T08:00:00Z" },
};

let restoreFails: boolean;
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  restoreFails = false;
  localStorage.clear();
  sessionStorage.clear();
  window.location.hash = "";
  fetcher = vi.fn(async (path: string) => {
    if (path.endsWith("/auth/session")) return restoreFails ? Response.json({}, { status: 401 }) : Response.json(credentials);
    if (path.endsWith("/auth/telegram")) return Response.json(credentials);
    if (path.endsWith("/categories")) return Response.json([category]);
    if (path.includes("/items?")) return Response.json({ items: [dish], total: 1, limit: 24, offset: 0 });
    if (path.endsWith(dish.id)) return Response.json(dish);
    throw new Error("Unexpected request " + path);
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AuthProvider><MenuApp /></AuthProvider></QueryClientProvider>);
}

test("returning to checkout keeps the same in-flight checkout screen mounted", async () => {
  localStorage.setItem(CART_KEY, JSON.stringify({ version: 1, items: [{ id: dish.id, quantity: 1 }] }));
  mount();
  const user = userEvent.setup();
  // Session recovery and saved basket hydration can exceed the default one-second query timeout during a parallel Docker build.
  await user.click(await screen.findByRole("button", { name: /Корзина · 1/ }, { timeout: 5_000 }));
  const choose = screen.getByRole<HTMLButtonElement>("button", { name: "Выбрать время" });
  await waitFor(() => expect(choose.disabled).toBe(false));
  await user.click(choose);
  await user.click(screen.getByRole("button", { name: "Начать проверку запроса" }));
  await user.click(screen.getByRole("button", { name: "К корзине" }));
  expect(screen.queryByRole("button", { name: "Сохраняем исходный запрос" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Выбрать время" }));
  expect(screen.getByRole("button", { name: "Сохраняем исходный запрос" })).toBeTruthy();
}, 10_000);

test("Telegram launch gives the existing auth provider the signed data and lands on the menu", async () => {
  restoreFails = true;
  window.location.hash = "tgWebAppData=synthetic-test-vector";
  mount();
  expect(screen.getByRole("heading", { name: "Открываем меню" })).toBeTruthy();
  await screen.findByRole("heading", { name: "Что на обед?" });
  expect(fetcher).toHaveBeenCalledWith("/api/v1/users/auth/telegram", expect.objectContaining({
    method: "POST", body: JSON.stringify({ init_data: "synthetic-test-vector" }),
  }));
  expect(window.location.hash).toBe("#tgWebAppData=synthetic-test-vector");
});

test("Back restores the selected category and originating card after a detail read", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Супы" }));
  const card = await screen.findByRole("button", { name: /Подробнее: Борщ/ });
  await user.click(card);
  const details = await screen.findByRole("region", { name: "Борщ" });
  await within(details).findByText("Свекольный суп.");
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/items/" + dish.id))).toBe(true);
  await user.click(within(details).getByRole("button", { name: "Закрыть блюдо" }));
  expect(screen.getByRole("button", { name: "Супы" }).getAttribute("aria-pressed")).toBe("true");
  expect(document.activeElement).toBe(card);
});

test("the dish stepper keeps the saved quantity and applies edits as the new total", async () => {
  mount();
  const user = userEvent.setup();
  const cards = await screen.findAllByRole("button", { name: /Подробнее: Борщ/ });
  await user.click(cards[0]);
  const details = await screen.findByRole("region", { name: "Борщ" });
  await within(details).findByText("Свекольный суп.");
  const less = within(details).getByRole<HTMLButtonElement>("button", { name: "Уменьшить количество" });
  expect(less.disabled).toBe(true);
  await user.click(within(details).getByRole("button", { name: "Увеличить количество" }));
  expect(JSON.parse(localStorage.getItem(CART_KEY)!).items).toEqual([]);
  await user.click(within(details).getByRole("button", { name: /количество 2, 300/ }));
  expect(within(details).getByRole("button", { name: "Перейти в корзину" })).toBeTruthy();
  expect(JSON.parse(localStorage.getItem(CART_KEY)!).items).toEqual([{ id: dish.id, quantity: 2 }]);
  expect(within(within(details).getByRole("group", { name: "Количество порций" })).getByText("2")).toBeTruthy();
  await user.click(within(details).getByRole("button", { name: "Закрыть блюдо" }));
  await user.click(cards[0]);

  const reopened = await screen.findByRole("region", { name: "Борщ" });
  expect(within(within(reopened).getByRole("group", { name: "Количество порций" })).getByText("2")).toBeTruthy();
  await user.click(within(reopened).getByRole("button", { name: "Уменьшить количество" }));
  const save = within(reopened).getByRole<HTMLButtonElement>("button", { name: /Обновить количество:.*количество 1, 150/ });
  await waitFor(() => expect(save.disabled).toBe(false));
  await user.click(save);
  expect(JSON.parse(localStorage.getItem(CART_KEY)!).items).toEqual([{ id: dish.id, quantity: 1 }]);
  await user.click(within(reopened).getByRole("button", { name: "Уменьшить количество" }));
  await user.click(within(reopened).getByRole("button", { name: "Убрать из корзины" }));
  expect(JSON.parse(localStorage.getItem(CART_KEY)!).items).toEqual([]);
});

test("featured card, category card, basket and dish agree on the portion count", async () => {
  mount();
  const user = userEvent.setup();
  const buttons = await screen.findAllByRole("button", { name: "Добавить Борщ в корзину" });
  expect(buttons).toHaveLength(2);
  await user.click(buttons[0]);
  await user.click(buttons[1]);
  expect(screen.getAllByRole("button", { name: "Добавить Борщ в корзину, в корзине 2" })).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: /Корзина · 2/ }));
  expect(screen.getByText("2 порции")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Уменьшить количество: Борщ" }));
  expect(screen.getByText("1 порция")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Назад" }));
  expect(screen.getAllByRole("button", { name: "Добавить Борщ в корзину, в корзине 1" })).toHaveLength(2);
  await user.click(screen.getAllByRole("button", { name: /Подробнее: Борщ/ })[1]);
  expect(within(screen.getByRole("group", { name: "Количество порций" })).getByText("1")).toBeTruthy();
});

test("an existing READY notification link opens history after session recovery", async () => {
  window.location.hash = "orders";
  mount();
  const history = await screen.findByText("История аккаунта");
  await waitFor(() => expect(history.closest("[hidden]")).toBeNull());
});

test("an existing basket link opens checkout entry after session recovery", async () => {
  window.location.hash = "cart";
  mount();
  await screen.findByRole("heading", { name: "Корзина пуста" });
});

test("category changes carry the current scroll offset and restore each saved position", async () => {
  mount();
  const user = userEvent.setup();
  const feed = await screen.findByRole("region", { name: "Меню столовой" });
  await screen.findAllByRole("button", { name: /Подробнее: Борщ/ });
  feed.scrollTop = 183;
  await user.click(screen.getByRole("button", { name: "Супы" }));
  await screen.findByRole("button", { name: /Подробнее: Борщ/ });
  expect(feed.scrollTop).toBe(183);

  feed.scrollTop = 240;
  await user.click(screen.getByRole("button", { name: "На обед" }));
  await screen.findAllByRole("button", { name: /Подробнее: Борщ/ });
  expect(feed.scrollTop).toBe(183);
  await user.click(screen.getByRole("button", { name: "Супы" }));
  await screen.findByRole("button", { name: /Подробнее: Борщ/ });
  expect(feed.scrollTop).toBe(240);
});
