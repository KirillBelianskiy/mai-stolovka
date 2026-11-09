import { apiUrl } from "./api-origin.ts";

import { AuthApiError } from "./auth.ts";
import type { CheckoutIntent } from "./checkout";

const MAX = 2 ** 31 - 1;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const STATUS_LABELS = {
  PENDING: "Ожидает приготовления",
  PREPARING: "Готовится",
  READY: "Готов к выдаче",
  COMPLETED: "Выдан",
  CANCELLED: "Отменён",
} as const;
export type OrderStatus = keyof typeof STATUS_LABELS;
export type PaymentStatus = "NOT_REQUIRED" | "DEMO_PAID" | "DEMO_REFUNDED" | "UNKNOWN";
export function paymentLabel(status: PaymentStatus): string {
  return {
    NOT_REQUIRED: "Оплата не требовалась",
    DEMO_PAID: "Оплачено демосредствами",
    DEMO_REFUNDED: "Демосредства возвращены",
    UNKNOWN: "Данные об оплате не получены",
  }[status];
}
export type Wallet = {
  user_id: string;
  balance: number;
  currency: "RUB";
  demo: true;
  checkout_payment_enabled: boolean;
};
export type Order = {
  id: string;
  order_number: string;
  user_id: string;
  slot_id: string;
  slot_start_time: string;
  slot_end_time: string;
  status: OrderStatus;
  payment_status: PaymentStatus;
  total_amount: number;
  version: number;
  created_at: string;
  updated_at: string;
  items: {
    id: string;
    menu_item_id: string;
    quantity: number;
    price_at_moment: number;
    name_at_moment: string;
  }[];
};
export type OrderPage = {
  items: Order[];
  total: number;
  offset: number;
  limit: number;
};
export type Slot = {
  id: string;
  start_time: string;
  end_time: string;
  capacity: number;
  current_orders: number;
  remaining_capacity: number;
};
export class OrderApiError extends AuthApiError {
  readonly code: string | null;
  readonly totalAmount: number | null;
  constructor(
    status: number,
    code: string | null,
    totalAmount: number | null = null,
  ) {
    super("Order request failed", status);
    this.name = "OrderApiError";
    this.code = code;
    this.totalAmount = totalAmount;
  }
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid order data");
  return value as Record<string, unknown>;
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !UUID.test(value))
    throw new Error("Invalid order ID");
  return value.toLowerCase();
}
function integer(value: unknown, min = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < min ||
    value > MAX
  )
    throw new Error("Invalid order integer");
  return value;
}
function text(value: unknown, max: number): string {
  if (typeof value !== "string" || !value.length || value.length > max)
    throw new Error("Invalid order text");
  return value;
}
function date(value: unknown): string {
  const s = text(value, 64);
  if (!/(Z|[+-]\d\d:\d\d)$/.test(s) || !Number.isFinite(Date.parse(s)))
    throw new Error("Invalid order time");
  return s;
}
export function decodeOrder(value: unknown, accountId: string): Order {
  const row = object(value);
  const payment = row.payment_status === undefined ? "UNKNOWN" : row.payment_status;
  if ((row.payment_status !== undefined && !["NOT_REQUIRED", "DEMO_PAID", "DEMO_REFUNDED"].includes(payment as string)) ||
      (payment === "DEMO_REFUNDED" && row.status !== "CANCELLED"))
    throw new Error("Invalid payment evidence");
  if (
    uuid(row.user_id) !== accountId ||
    typeof row.status !== "string" ||
    !Object.hasOwn(STATUS_LABELS, row.status) ||
    !Array.isArray(row.items) ||
    row.items.length < 1 ||
    row.items.length > 100
  )
    throw new Error("Invalid own order");
  const items = row.items.map((value) => {
    const r = object(value);
    return {
      id: uuid(r.id),
      menu_item_id: uuid(r.menu_item_id),
      quantity: integer(r.quantity, 1),
      price_at_moment: integer(r.price_at_moment),
      name_at_moment: text(r.name_at_moment, 256),
    };
  });
  const total = integer(row.total_amount);
  if (
    items.reduce(
      (sum, line) => sum + line.price_at_moment * line.quantity,
      0,
    ) !== total ||
    new Set(items.map((i) => i.menu_item_id)).size !== items.length
  )
    throw new Error("Invalid order total");
  const start = date(row.slot_start_time),
    end = date(row.slot_end_time);
  if (Date.parse(start) >= Date.parse(end))
    throw new Error("Invalid slot interval");
  return {
    id: uuid(row.id),
    order_number: text(row.order_number, 64),
    user_id: uuid(row.user_id),
    slot_id: uuid(row.slot_id),
    slot_start_time: start,
    slot_end_time: end,
    status: row.status as OrderStatus,
    payment_status: payment as PaymentStatus,
    total_amount: total,
    version: integer(row.version, 1),
    created_at: date(row.created_at),
    updated_at: date(row.updated_at),
    items,
  };
}
async function request(
  path: string,
  token: string,
  init: RequestInit = {},
  fetcher: typeof fetch = fetch,
): Promise<unknown> {
  const response = await fetcher(apiUrl(`/api/v1/orders${path}`), {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    signal: init.signal
      ? AbortSignal.any([init.signal, AbortSignal.timeout(12000)])
      : AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    let code: string | null = null,
      total: number | null = null;
    try {
      const detail = object(object(await response.json()).detail);
      if (typeof detail.code === "string") code = detail.code;
      if (typeof detail.total_amount === "number")
        total = integer(detail.total_amount);
    } catch {
      /* Non-contract failures remain explicit HTTP errors. */
    }
    throw new OrderApiError(response.status, code, total);
  }
  return response.json();
}
export async function loadWallet(
  accountId: string,
  token: string,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<Wallet> {
  const row = object(await request("/wallet", token, { signal }, fetcher));
  if (uuid(row.user_id) !== accountId || row.demo !== true || row.currency !== "RUB" ||
      typeof row.checkout_payment_enabled !== "boolean")
    throw new Error("Invalid own demo wallet");
  return { user_id: uuid(row.user_id), balance: integer(row.balance), currency: "RUB",
    demo: true, checkout_payment_enabled: row.checkout_payment_enabled };
}
export async function createOrder(
  intent: CheckoutIntent,
  token: string,
  fetcher: typeof fetch = fetch,
): Promise<Order> {
  const order = decodeOrder(
    await request(
      "/",
      token,
      {
        method: "POST",
        headers: { "Idempotency-Key": intent.key },
        body: JSON.stringify(intent.body),
      },
      fetcher,
    ),
    intent.account_id,
  );
  const actual = order.items
    .map((i) => ({ menu_item_id: i.menu_item_id, quantity: i.quantity }))
    .sort((a, b) => a.menu_item_id.localeCompare(b.menu_item_id));
  if (
    order.slot_id !== intent.body.slot_id ||
    order.total_amount !== intent.body.expected_total_amount ||
    JSON.stringify(actual) !== JSON.stringify(intent.body.items)
  )
    throw new Error("Order response does not match intent");
  return order;
}
export async function loadOrders(
  accountId: string,
  token: string,
  offset = 0,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<OrderPage> {
  const row = object(
    await request(
      `/?limit=10&offset=${integer(offset)}`,
      token,
      { signal },
      fetcher,
    ),
  );
  if (
    !Array.isArray(row.items) ||
    row.items.length > 10 ||
    integer(row.limit) !== 10 ||
    integer(row.offset) !== offset
  )
    throw new Error("Invalid order page");
  const items = row.items.map((value) => decodeOrder(value, accountId));
  const total = integer(row.total);
  if (
    new Set(items.map((i) => i.id)).size !== items.length ||
    total < items.length
  )
    throw new Error("Invalid order page");
  return { items, total, offset, limit: 10 };
}
export async function loadOrder(
  id: string,
  accountId: string,
  token: string,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<Order> {
  const order = decodeOrder(
    await request(`/${uuid(id)}`, token, { signal }, fetcher),
    accountId,
  );
  if (order.id !== id) throw new Error("Wrong order response");
  return order;
}
export async function cancelOrder(
  order: Order,
  accountId: string,
  token: string,
  fetcher: typeof fetch = fetch,
): Promise<Order> {
  const result = decodeOrder(
    await request(
      `/${uuid(order.id)}/cancel`,
      token,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: integer(order.version, 1) }),
      },
      fetcher,
    ),
    accountId,
  );
  if (
    result.id !== order.id ||
    result.status !== "CANCELLED" ||
    result.version < order.version
  )
    throw new Error("Invalid cancellation response");
  return result;
}
export async function loadSlots(
  token: string,
  offset = 0,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<Slot[]> {
  const values = await request(
    `/slots?limit=50&offset=${integer(offset)}`,
    token,
    { signal },
    fetcher,
  );
  if (!Array.isArray(values) || values.length > 50)
    throw new Error("Invalid slots");
  const slots = values.map((value) => {
    const r = object(value);
    const slot = {
      id: uuid(r.id),
      start_time: date(r.start_time),
      end_time: date(r.end_time),
      capacity: integer(r.capacity, 1),
      current_orders: integer(r.current_orders),
      remaining_capacity: integer(r.remaining_capacity),
    };
    if (
      slot.capacity - slot.current_orders !== slot.remaining_capacity ||
      Date.parse(slot.start_time) >= Date.parse(slot.end_time)
    )
      throw new Error("Invalid slot capacity");
    return slot;
  });
  if (new Set(slots.map((s) => s.id)).size !== slots.length)
    throw new Error("Duplicate slots");
  return slots;
}
export function canCancel(
  order: Order,
  accountId: string,
  now = Date.now(),
): boolean {
  return (
    order.user_id === accountId &&
    order.status === "PENDING" &&
    Date.parse(order.slot_start_time) > now
  );
}
export function formatSlot(start: string, end: string): string {
  const day = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(start));
  const time = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
  });
  const endDay = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(end));
  return `${day}, ${time.format(new Date(start))}–${day === endDay ? "" : endDay + ", "}${time.format(new Date(end))} МСК`;
}
export function orderFailure(error: unknown): string {
  if (error instanceof OrderApiError) {
    const messages: Record<string, string> = {
      PRICE_CHANGED: "Цена изменилась. Подтвердите новую сумму перед заказом.",
      SLOT_FULL: "Все места заняты. Выберите другое время.",
      SLOT_CLOSED: "Приём заказов на это время завершён.",
      SLOT_STARTED: "Время выдачи уже началось. Отмена недоступна.",
      SLOT_NOT_FOUND: "Это время больше недоступно. Выберите другое.",
      VERSION_CONFLICT:
        "Заказ изменился. Обновите статус перед следующим действием.",
      CANNOT_CANCEL: "Заказ уже готовится или выдан — отменить его нельзя.",
      INSUFFICIENT_FUNDS:
        "На демобалансе недостаточно средств. Пополните его перед новым заказом.",
      IDEMPOTENCY_CONFLICT:
        "Сохранённый запрос не совпадает с ранее отправленным. Проверьте историю заказов.",
      ITEM_UNAVAILABLE: "Одно из блюд недоступно. Обновите меню.",
      DISH_UNAVAILABLE: "Одно из блюд недоступно. Обновите меню.",
      MENU_ITEM_NOT_FOUND: "Одно из блюд больше недоступно. Обновите меню.",
    };
    if (error.code && messages[error.code]) return messages[error.code];
    if (error.status === 401) return "Войдите в аккаунт, чтобы продолжить.";
    if (error.status === 403) return "Это действие недоступно вашему аккаунту.";
    if (error.status === 404)
      return "Заказ не найден или недоступен этому аккаунту.";
  }
  return "Не удалось подтвердить результат. Проверьте подключение и обновите данные.";
}
