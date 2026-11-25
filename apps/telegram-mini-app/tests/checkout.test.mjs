import assert from "node:assert/strict";
import test from "node:test";
import {
  createIntent,
  readIntent,
  persistIntent,
  removeIntent,
  JOURNAL_KEY,
} from "../src/lib/checkout.ts";
import {
  createOrder,
  decodeOrder,
  formatSlot,
  canCancel,
  loadOrders,
  OrderApiError,
} from "../src/lib/orders.ts";

const user = "00000000-0000-4000-8000-000000000001";
const slot = "00000000-0000-4000-8000-000000000002";
const dish = "00000000-0000-4000-8000-000000000003";
const key = "00000000-0000-4000-8000-000000000004";
const order = {
  id: key,
  user_id: user,
  slot_id: slot,
  order_number: "MAI-000001",
  status: "PENDING",
  version: 1,
  total_amount: 12000,
  slot_start_time: "2030-11-04T09:00:00Z",
  slot_end_time: "2030-11-04T09:30:00Z",
  created_at: "2030-11-04T08:00:00Z",
  updated_at: "2030-11-04T08:00:00Z",
  items: [
    {
      id: user,
      menu_item_id: dish,
      quantity: 1,
      price_at_moment: 12000,
      name_at_moment: "Суп",
    },
  ],
};
function storage() {
  const values = new Map();
  return {
    getItem: (k) => values.get(k) ?? null,
    setItem: (k, v) => values.set(k, v),
    removeItem: (k) => values.delete(k),
  };
}
function intent() {
  return createIntent(user, [{ id: dish, quantity: 1 }], slot, 12000, key);
}

test("persisted intent survives reload with original key/body and no credentials", async () => {
  const s = storage();
  const first = intent();
  persistIntent(s, first);
  const next = readIntent(s);
  assert.deepEqual(next, first);
  assert.deepEqual(Object.keys(JSON.parse(s.getItem(JOURNAL_KEY))).sort(), [
    "account_id",
    "body",
    "key",
    "version",
  ]);
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    return Response.json(order, { status: 201 });
  };
  await createOrder(first, "old-token", fetcher);
  await createOrder(next, "new-token", fetcher);
  assert.equal(calls[0].options.body, calls[1].options.body);
  assert.equal(calls[0].options.headers["Idempotency-Key"], key);
  assert.equal(calls[1].options.headers["Idempotency-Key"], key);
  assert.equal(calls[0].url, "/api/v1/orders/");
});
test("occupied, corrupted and unwritable journals cannot be replaced silently", () => {
  const s = storage();
  persistIntent(s, intent());
  assert.throws(() => persistIntent(s, { ...intent(), account_id: slot }));
  assert.throws(() => removeIntent(s, slot));
  assert.equal(readIntent(s).key, key);
  s.setItem(JOURNAL_KEY, '{"version":1}');
  assert.throws(() => readIntent(s));
  assert.throws(() =>
    persistIntent(
      { getItem: () => null, setItem: () => {}, removeItem: () => {} },
      intent(),
    ),
  );
});
test("unknown outcomes retain persisted intent and retry with exactly the same body", async () => {
  const s = storage();
  persistIntent(s, intent());
  const original = s.getItem(JOURNAL_KEY);
  await assert.rejects(
    createOrder(readIntent(s), "token", async () => {
      throw new TypeError("lost response");
    }),
  );
  assert.equal(s.getItem(JOURNAL_KEY), original);
  await assert.rejects(
    createOrder(
      readIntent(s),
      "token",
      async () => new Response("broken", { status: 201 }),
    ),
  );
  assert.equal(s.getItem(JOURNAL_KEY), original);
});
test("intent rejects extras, unsafe quantities, duplicate lines and empty carts", () => {
  const s = storage();
  s.setItem(
    JOURNAL_KEY,
    JSON.stringify({ ...intent(), access_token: "secret" }),
  );
  assert.throws(() => readIntent(s));
  for (const cart of [
    [],
    [{ id: dish, quantity: 0 }],
    [
      { id: dish, quantity: 1 },
      { id: dish, quantity: 1 },
    ],
  ])
    assert.throws(() => createIntent(user, cart, slot, 12000, key));
  assert.throws(() =>
    createIntent(user, [{ id: dish, quantity: 2 ** 32 }], slot, 12000, key),
  );
});
test("success and own history are validated against account and original order body", async () => {
  assert.throws(() => decodeOrder({ ...order, user_id: slot }, user));
  await assert.rejects(
    createOrder(intent(), "t", async () =>
      Response.json({ ...order, total_amount: 13000 }, { status: 201 }),
    ),
  );
  await assert.rejects(
    loadOrders(user, "t", 0, undefined, async () =>
      Response.json({
        items: [{ ...order, user_id: slot }],
        limit: 10,
        offset: 0,
        total: 1,
      }),
    ),
  );
});
test("server changed price is structured and never silently modifies the journal", async () => {
  const s = storage();
  persistIntent(s, intent());
  await assert.rejects(
    createOrder(readIntent(s), "t", async () =>
      Response.json(
        {
          detail: {
            code: "PRICE_CHANGED",
            message: "Confirm",
            total_amount: 13000,
          },
        },
        { status: 409 },
      ),
    ),
    (e) =>
      e instanceof OrderApiError &&
      e.code === "PRICE_CHANGED" &&
      e.totalAmount === 13000,
  );
  assert.equal(readIntent(s).body.expected_total_amount, 12000);
});
test("only pending own orders before slot start offer cancellation; timezone is explicit", () => {
  assert.equal(
    canCancel(order, user, Date.parse("2030-11-04T08:00:00Z")),
    true,
  );
  assert.equal(
    canCancel(order, slot, Date.parse("2030-11-04T08:00:00Z")),
    false,
  );
  assert.equal(canCancel({ ...order, status: "PREPARING" }, user, 0), false);
  assert.equal(
    canCancel(order, user, Date.parse(order.slot_start_time)),
    false,
  );
  assert.match(
    formatSlot(order.slot_start_time, order.slot_end_time),
    /12:00.*12:30.*МСК/,
  );
});
