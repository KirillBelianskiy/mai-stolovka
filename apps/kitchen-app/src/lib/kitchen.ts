export type StaffRole = "CLIENT" | "COOK" | "CASHIER" | "ADMIN";
export type OrderStatus =
  | "PENDING"
  | "PREPARING"
  | "READY"
  | "COMPLETED"
  | "CANCELLED";

export type UserProfile = {
  id: string;
  full_name: string;
  username: string | null;
  role: StaffRole;
};

export type LoginResponse = {
  access_token: string;
  expires_in: number;
  user: UserProfile;
};

export type Order = {
  id: string;
  order_number: string;
  user_id: string;
  slot_id: string;
  slot_start_time: string;
  slot_end_time: string;
  status: OrderStatus;
  total_amount: number;
  version: number;
  created_at: string;
  items: Array<{
    id: string;
    menu_item_id: string;
    quantity: number;
    price_at_moment: number;
    name_at_moment: string;
  }>;
};

export type OrderPage = {
  items: Order[];
  total: number;
  limit: number;
  offset: number;
};

export type StaffSession = {
  token: string;
  expiresAt: number;
  user: UserProfile;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export async function apiRequest<T>(
  path: string,
  token?: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Сервис недоступен. Проверьте сеть и повторите попытку.", 0);
  }

  if (!response.ok) {
    let message = response.status === 0
      ? "Сервис недоступен"
      : `Не удалось выполнить запрос (${response.status})`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as {
        detail?: string | { code?: string; message?: string };
      };
      if (typeof body.detail === "string") message = body.detail;
      if (typeof body.detail === "object" && body.detail !== null) {
        message = body.detail.message ?? message;
        code = body.detail.code;
      }
    } catch {
      // Keep the status-based message if the service returned no JSON body.
    }
    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function queueStatuses(role: StaffRole): OrderStatus[] {
  if (role === "CASHIER") return ["READY"];
  if (role === "COOK") return ["PENDING", "PREPARING"];
  return ["PENDING", "PREPARING", "READY"];
}

export function nextStatus(order: Order, role: StaffRole): OrderStatus | null {
  if (order.status === "PENDING" && ["COOK", "ADMIN"].includes(role)) {
    return "PREPARING";
  }
  if (order.status === "PREPARING" && ["COOK", "ADMIN"].includes(role)) {
    return "READY";
  }
  if (order.status === "READY" && ["CASHIER", "ADMIN"].includes(role)) {
    return "COMPLETED";
  }
  return null;
}

export function canCancel(order: Order, role: StaffRole): boolean {
  return role === "ADMIN" && ["PENDING", "PREPARING"].includes(order.status);
}

export function isStaffRole(role: StaffRole): boolean {
  return role === "COOK" || role === "CASHIER" || role === "ADMIN";
}
