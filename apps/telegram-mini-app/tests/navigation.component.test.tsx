import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MenuApp } from "../src/components/menu-app";

vi.mock("@/components/order-workspace", () => ({
  CheckoutPanel: function CheckoutProbe() {
    const [pending, setPending] = useState(false);
    return (
      <button onClick={() => setPending(true)}>
        {pending ? "Сохраняем исходный запрос" : "Начать проверку запроса"}
      </button>
    );
  },
  OrdersPanel: () => <section>История аккаунта</section>,
}));
vi.mock("@/components/profile-panel", () => ({
  ProfilePanel: () => <section>Профиль аккаунта</section>,
}));

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "menu";
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.includes("categories")
              ? []
              : { items: [], total: 0, limit: 24, offset: 0 },
          ),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MenuApp />
    </QueryClientProvider>,
  );
}
function navigate(hash: string) {
  window.location.hash = hash;
  fireEvent(window, new HashChangeEvent("hashchange"));
}

test("changing screens preserves the mounted checkout and hides private screens", async () => {
  mount();
  navigate("cart");
  fireEvent.click(
    screen.getByRole("button", { name: "Начать проверку запроса" }),
  );
  navigate("menu");
  expect(
    screen.queryByRole("button", { name: "Сохраняем исходный запрос" }),
  ).toBeNull();
  expect(
    screen.queryByText("История аккаунта")?.closest("[hidden]"),
  ).not.toBeNull();
  expect(
    screen.queryByText("Профиль аккаунта")?.closest("[hidden]"),
  ).not.toBeNull();
  navigate("cart");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Сохраняем исходный запрос" }),
    ).toBeTruthy(),
  );
});

test("a signed Telegram launch hash opens the menu", () => {
  window.location.hash = "tgWebAppData=synthetic-test-vector";
  mount();
  expect(screen.getByRole("heading", { name: "Меню на сегодня" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Меню" }).getAttribute("aria-current"),
  ).toBe("page");
});
