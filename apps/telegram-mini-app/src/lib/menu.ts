export const MAX_INTEGER = 2 ** 31 - 1;
export const CART_KEY = "mai-food:public-cart:v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type Category = { id: string; name: string; sort_order: number };
export type MenuItem = {
  id: string;
  category_id: string;
  name: string;
  price: number;
  description: string | null;
  image_url: string | null;
  is_available: boolean;
};
export type ItemPage = {
  items: MenuItem[];
  total: number;
  limit: number;
  offset: number;
};
export type CartLine = { id: string; quantity: number };

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("Invalid object");
  return value as Record<string, unknown>;
}
function integer(value: unknown, min = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < min ||
    value > MAX_INTEGER
  ) {
    throw new Error("Invalid integer");
  }
  return value;
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !UUID.test(value))
    throw new Error("Invalid UUID");
  return value.toLowerCase();
}
function text(value: unknown, max: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max)
    throw new Error("Invalid text");
  return value;
}
export function decodeItem(value: unknown): MenuItem {
  const row = record(value);
  if (row.is_available !== undefined && typeof row.is_available !== "boolean")
    throw new Error("Invalid availability");
  return {
    id: uuid(row.id),
    category_id: uuid(row.category_id),
    name: text(row.name, 256),
    price: integer(row.price),
    is_available: row.is_available !== false,
    description:
      row.description == null
        ? null
        : row.description === ""
          ? ""
          : text(row.description, 10000),
    image_url:
      row.image_url == null
        ? null
        : row.image_url === ""
          ? ""
          : text(row.image_url, 2048),
  };
}
export function decodeItemPage(value: unknown): ItemPage {
  const row = record(value);
  if (!Array.isArray(row.items) || row.items.length > 100)
    throw new Error("Invalid page");
  const items = row.items.map(decodeItem);
  const total = integer(row.total),
    limit = integer(row.limit, 1),
    offset = integer(row.offset);
  if (
    limit > 100 ||
    items.length > limit ||
    total < items.length ||
    new Set(items.map((item) => item.id)).size !== items.length
  ) {
    throw new Error("Invalid pagination");
  }
  return { items, total, limit, offset };
}
export function decodeCategories(value: unknown): Category[] {
  if (!Array.isArray(value)) throw new Error("Invalid categories");
  const categories = value.map((value) => {
    const row = record(value);
    if (
      row.sort_order !== undefined &&
      (typeof row.sort_order !== "number" || !Number.isInteger(row.sort_order))
    )
      throw new Error("Invalid category order");
    return {
      id: uuid(row.id),
      name: text(row.name, 128),
      sort_order: (row.sort_order as number | undefined) ?? 0,
    };
  });
  if (
    new Set(categories.map((category) => category.id)).size !==
    categories.length
  )
    throw new Error("Duplicate category");
  return categories.sort(
    (a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id),
  );
}

async function get(
  path: string,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<unknown> {
  const response = await fetcher(path, {
    signal,
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!response.ok) {
    if (response.status === 404) throw new Error("Блюдо больше недоступно.");
    throw new Error("Меню временно недоступно. Попробуйте ещё раз.");
  }
  return response.json();
}
export async function loadCategories(
  signal?: AbortSignal,
): Promise<Category[]> {
  return decodeCategories(await get("/api/v1/menu/categories", signal));
}
export async function loadItems(
  categoryId: string | null,
  offset: number,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<ItemPage> {
  const params = new URLSearchParams({
    limit: "24",
    offset: String(integer(offset)),
  });
  if (categoryId) params.set("category_id", uuid(categoryId));
  const page = decodeItemPage(
    await get(`/api/v1/menu/items?${params}`, signal, fetcher),
  );
  if (
    page.offset !== offset ||
    page.limit !== 24 ||
    (categoryId && page.items.some((item) => item.category_id !== categoryId))
  )
    throw new Error("Invalid page response");
  return page;
}
export async function loadItem(
  id: string,
  signal?: AbortSignal,
): Promise<MenuItem> {
  const item = decodeItem(await get(`/api/v1/menu/items/${uuid(id)}`, signal));
  if (item.id !== id) throw new Error("Invalid item response");
  return item;
}

export function setQuantity(
  cart: CartLine[],
  id: string,
  quantity: number,
): CartLine[] {
  id = uuid(id);
  integer(quantity);
  const next = cart.filter((line) => line.id !== id);
  if (quantity > 0) next.push({ id, quantity });
  if (next.length > 100)
    throw new Error("В корзине может быть не больше 100 разных блюд.");
  return next.sort((a, b) => a.id.localeCompare(b.id));
}
export function addToCart(cart: CartLine[], id: string): CartLine[] {
  return setQuantity(
    cart,
    id,
    (cart.find((line) => line.id === id)?.quantity ?? 0) + 1,
  );
}
export function saveCart(cart: CartLine[]): string {
  return JSON.stringify({
    version: 1,
    items: cart.map(({ id, quantity }) => ({ id, quantity })),
  });
}
export function decodeCart(raw: string): CartLine[] {
  if (raw.length > 20000) throw new Error("Cart exceeds size limit");
  const value = record(JSON.parse(raw));
  if (
    Object.keys(value).sort().join() !== "items,version" ||
    value.version !== 1 ||
    !Array.isArray(value.items) ||
    value.items.length > 100
  )
    throw new Error("Invalid cart");
  const items = value.items.map((value) => {
    const row = record(value);
    if (Object.keys(row).sort().join() !== "id,quantity")
      throw new Error("Invalid cart line");
    return { id: uuid(row.id), quantity: integer(row.quantity, 1) };
  });
  if (new Set(items.map((item) => item.id)).size !== items.length)
    throw new Error("Duplicate cart line");
  return items;
}
export function cartTotal(cart: CartLine[], items: MenuItem[]): number | null {
  let total = 0;
  const current = new Map(items.map((item) => [item.id, item]));
  for (const line of cart) {
    const item = current.get(line.id);
    if (!item || !item.is_available) return null;
    total += item.price * line.quantity;
    if (!Number.isSafeInteger(total) || total > MAX_INTEGER) return null;
  }
  return total;
}
export function money(kopecks: number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    minimumFractionDigits: kopecks % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(kopecks / 100);
}
export function imageUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
