import assert from "node:assert/strict";
import test from "node:test";
import {
  addToCart,
  cartTotal,
  decodeCart,
  decodeItemPage,
  loadItems,
  imageUrl,
  money,
  saveCart,
  setQuantity,
} from "../src/lib/menu.ts";

const id = "6c375712-23bc-4aa4-85d2-1950608520f0";
const category = "c27fe0b5-293a-43d5-8c14-d4ba66a99428";
const item = {
  id,
  category_id: category,
  name: "Суп",
  price: 12345,
  is_available: true,
};

test("money keeps kopecks and unsafe image protocols are never rendered", () => {
  assert.match(money(13550), /135,50/);
  assert.match(money(100), /1\s*₽/);
  assert.equal(imageUrl("javascript:alert(1)"), undefined);
  assert.equal(imageUrl("data:image/svg+xml,unsafe"), undefined);
  assert.equal(
    imageUrl("https://example.org/dish.jpg"),
    "https://example.org/dish.jpg",
  );
});

test("cart persists only dish UUIDs and quantities; malformed input is rejected", () => {
  const cart = addToCart([], id);
  assert.deepEqual(decodeCart(saveCart(cart)), [{ id, quantity: 1 }]);
  for (const value of [
    "not-json",
    JSON.stringify({ version: 2, items: cart }),
    JSON.stringify({ version: 1, items: [{ id, quantity: -1 }] }),
    JSON.stringify({ version: 1, items: [{ id, quantity: 1.5 }] }),
    JSON.stringify({ version: 1, items: [{ id, quantity: true }] }),
    JSON.stringify({ version: 1, items: [{ id: "bad", quantity: 1 }] }),
    JSON.stringify({ version: 1, items: [...cart, ...cart] }),
    JSON.stringify({ version: 1, items: cart, access_token: "never-preserve" }),
  ])
    assert.throws(() => decodeCart(value));
});

test("quantities are bounded, zero removes, and distinct-line cap is enforced", () => {
  assert.deepEqual(addToCart(addToCart([], id), id), [{ id, quantity: 2 }]);
  assert.deepEqual(setQuantity([{ id, quantity: 2 }], id, 0), []);
  assert.throws(() => setQuantity([], id, 1.5));
  assert.throws(() => setQuantity([], id, 2 ** 31));
  const full = Array.from({ length: 100 }, (_, i) => ({
    id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
    quantity: 1,
  }));
  assert.throws(() => addToCart(full, id));
});

test("total uses current integer kopecks and refuses incomplete or overflowing totals", () => {
  assert.equal(cartTotal([{ id, quantity: 2 }], [item]), 24690);
  assert.equal(
    cartTotal([{ id, quantity: 2 }], [{ ...item, price: 100 }]),
    200,
  );
  assert.equal(cartTotal([{ id, quantity: 2 }], []), null);
  assert.equal(
    cartTotal([{ id, quantity: 2 }], [{ ...item, is_available: false }]),
    null,
  );
  assert.equal(
    cartTotal([{ id, quantity: 2 }], [{ ...item, price: 2 ** 31 - 1 }]),
    null,
  );
});

test("menu responses are validated rather than trusting success status", () => {
  const page = { items: [item], total: 1, limit: 24, offset: 0 };
  assert.equal(decodeItemPage(page).items[0].name, "Суп");
  for (const value of [
    { ...page, items: [{ ...item, price: "123" }] },
    { ...page, items: [{ ...item, price: -1 }] },
    { ...page, items: [{ ...item, price: 12.5 }] },
    { ...page, items: [{ ...item, id: "bad" }] },
    { ...page, total: -1 },
    { ...page, items: [item, item], total: 2 },
  ])
    assert.throws(() => decodeItemPage(value));
});

test("public fetch sends only same-origin menu query, cancellation and no credentials", async () => {
  const controller = new AbortController();
  let request;
  await loadItems(category, 24, controller.signal, async (url, options) => {
    request = { url, options };
    return Response.json({ items: [], total: 24, limit: 24, offset: 24 });
  });
  assert.equal(
    request.url,
    `/api/v1/menu/items?limit=24&offset=24&category_id=${category}`,
  );
  assert.equal(request.options.signal, controller.signal);
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.cache, "no-store");
  assert.equal(request.options.headers, undefined);
  await assert.rejects(
    () =>
      loadItems(
        null,
        0,
        controller.signal,
        async () => new Response("private backend details", { status: 503 }),
      ),
    (error) =>
      error.message === "Меню временно недоступно. Попробуйте ещё раз.",
  );
});
