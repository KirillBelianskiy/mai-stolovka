import assert from "node:assert/strict";
import test from "node:test";
import { loadWallet, decodeOrder, paymentLabel } from "../src/lib/orders.ts";

const user = "00000000-0000-4000-8000-000000000001";
const other = "00000000-0000-4000-8000-000000000002";
const wallet = { user_id: user, balance: 12345, currency: "RUB", demo: true, checkout_payment_enabled: true };
const order = {
  id: user, user_id: user, slot_id: other, order_number: "MAI-1", status: "PENDING", version: 1,
  total_amount: 12345, slot_start_time: "2099-01-01T10:00:00Z", slot_end_time: "2099-01-01T11:00:00Z",
  created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z",
  items: [{ id: user, menu_item_id: other, quantity: 1, price_at_moment: 12345, name_at_moment: "Обед" }],
};
test("wallet reads only authoritative own synthetic RUB funds with no caching", async () => {
  const result = await loadWallet(user, "token", undefined, async (url, init) => {
    assert.equal(url, "/api/v1/orders/wallet");
    assert.equal(init.cache, "no-store");
    assert.equal(init.headers.Authorization, "Bearer token");
    return Response.json(wallet);
  });
  assert.deepEqual(result, wallet);
});
test("wallet rejects foreign identity, unsafe amounts and ambiguous payment mode", async () => {
  for (const patch of [{ user_id: other }, { balance: -1 }, { balance: 1.5 }, { balance: 2 ** 31 }, { demo: false }, { currency: "USD" }, { checkout_payment_enabled: "true" }]) {
    await assert.rejects(loadWallet(user, "t", undefined, async () => Response.json({ ...wallet, ...patch })));
  }
  await assert.rejects(loadWallet(user, "t", undefined, async () => new Response("unavailable", { status: 503 })));
});
test("payment evidence distinguishes paid, refunded, not required and missing legacy evidence", () => {
  for (const status of ["NOT_REQUIRED", "DEMO_PAID", "DEMO_REFUNDED"]) {
    const value = decodeOrder({ ...order, status: status === "DEMO_REFUNDED" ? "CANCELLED" : "PENDING", payment_status: status }, user);
    assert.equal(value.payment_status, status);
    assert.ok(paymentLabel(value.payment_status));
  }
  assert.equal(decodeOrder(order, user).payment_status, "UNKNOWN");
  assert.match(paymentLabel("UNKNOWN"), /не получены/);
  for (const payment_status of ["PAID", null, true, "DEMO_REFUNDED"]) assert.throws(() => decodeOrder({ ...order, payment_status }, user));
});
