import type { CartLine } from "./menu";

export const JOURNAL_KEY = "mai-food:checkout:v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX = 2 ** 31 - 1;
export type OrderBody = {
  slot_id: string;
  items: { menu_item_id: string; quantity: number }[];
  expected_total_amount: number;
};
export type CheckoutIntent = {
  version: 1;
  account_id: string;
  key: string;
  body: OrderBody;
};
export type IntentStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid intent");
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: string) {
  if (Object.keys(value).sort().join() !== expected)
    throw new Error("Unexpected intent data");
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !UUID.test(value))
    throw new Error("Invalid intent identifier");
  return value.toLowerCase();
}
function integer(value: unknown, min: number): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < min ||
    value > MAX
  )
    throw new Error("Invalid intent amount");
  return value;
}
export function validateIntent(value: unknown): CheckoutIntent {
  const row = object(value);
  keys(row, "account_id,body,key,version");
  if (row.version !== 1) throw new Error("Unsupported intent");
  const body = object(row.body);
  keys(body, "expected_total_amount,items,slot_id");
  if (
    !Array.isArray(body.items) ||
    body.items.length < 1 ||
    body.items.length > 100
  )
    throw new Error("Invalid cart");
  const items = body.items
    .map((value) => {
      const line = object(value);
      keys(line, "menu_item_id,quantity");
      return Object.freeze({
        menu_item_id: uuid(line.menu_item_id),
        quantity: integer(line.quantity, 1),
      });
    })
    .sort((a, b) => a.menu_item_id.localeCompare(b.menu_item_id));
  if (new Set(items.map((line) => line.menu_item_id)).size !== items.length)
    throw new Error("Duplicate intent lines");
  return Object.freeze({
    version: 1,
    account_id: uuid(row.account_id),
    key: uuid(row.key),
    body: Object.freeze({
      slot_id: uuid(body.slot_id),
      items: Object.freeze(items) as unknown as OrderBody["items"],
      expected_total_amount: integer(body.expected_total_amount, 0),
    }),
  });
}
export function createIntent(
  accountId: string,
  cart: CartLine[],
  slotId: string,
  total: number,
  key = crypto.randomUUID(),
): CheckoutIntent {
  return validateIntent({
    version: 1,
    account_id: accountId,
    key,
    body: {
      slot_id: slotId,
      items: cart.map((line) => ({
        menu_item_id: line.id,
        quantity: line.quantity,
      })),
      expected_total_amount: total,
    },
  });
}
export function readIntent(storage: IntentStorage): CheckoutIntent | null {
  const raw = storage.getItem(JOURNAL_KEY);
  if (raw === null) return null;
  if (raw.length > 20000) throw new Error("Intent exceeds size limit");
  return validateIntent(JSON.parse(raw));
}
export function persistIntent(
  storage: IntentStorage,
  intent: CheckoutIntent,
): void {
  const safe = validateIntent(intent),
    raw = JSON.stringify(safe),
    existing = readIntent(storage);
  if (existing && JSON.stringify(existing) !== raw)
    throw new Error("Another intent is unresolved");
  storage.setItem(JOURNAL_KEY, raw);
  if (storage.getItem(JOURNAL_KEY) !== raw)
    throw new Error("Intent could not be persisted");
}
export function removeIntent(
  storage: IntentStorage,
  expectedKey?: string,
): void {
  if (expectedKey && readIntent(storage)?.key !== expectedKey)
    throw new Error("Intent changed");
  storage.removeItem(JOURNAL_KEY);
  if (storage.getItem(JOURNAL_KEY) !== null)
    throw new Error("Intent could not be removed");
}
