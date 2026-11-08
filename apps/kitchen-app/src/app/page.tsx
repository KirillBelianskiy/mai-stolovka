"use client";

import {
  AlertCircle,
  ArrowRight,
  Check,
  ChefHat,
  Clock3,
  LogOut,
  RefreshCw,
  Utensils,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import {
  apiRequest,
  ApiError,
  canCancel,
  isStaffRole,
  nextStatus,
  queueStatuses,
  type LoginResponse,
  type Order,
  type OrderPage,
  type OrderStatus,
  type StaffRole,
  type StaffSession,
  type UserProfile,
} from "@/lib/kitchen";

const SESSION_KEY = "mai-food-kitchen-session";
const STATUS_LABELS: Record<OrderStatus, string> = {
  PENDING: "Ожидает",
  PREPARING: "Готовится",
  READY: "Готов к выдаче",
  COMPLETED: "Выдан",
  CANCELLED: "Отменён",
};
const ROLE_LABELS: Record<StaffRole, string> = {
  CLIENT: "Клиент",
  COOK: "Повар",
  CASHIER: "Кассир",
  ADMIN: "Администратор",
};

function formatTime(value: string, includeDate = false): string {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    ...(includeDate ? { day: "numeric", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatMoney(kopecks: number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  }).format(kopecks / 100);
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Не удалось выполнить действие. Попробуйте ещё раз.";
}

function LoginPanel({
  message,
  onLogin,
}: {
  message: string;
  onLogin: (session: StaffSession) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const result = await apiRequest<LoginResponse>("/users/auth/staff", undefined, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      if (!isStaffRole(result.user.role)) {
        throw new Error("Вход в рабочее место доступен только сотрудникам.");
      }
      const session = {
        token: result.access_token,
        expiresAt: Date.now() + result.expires_in * 1000,
        user: result.user,
      };
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
      onLogin(session);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand-mark"><Utensils size={21} strokeWidth={2.2} /></div>
        <p className="eyebrow">МАИ · СТОЛОВАЯ</p>
        <h1 id="login-title">Вход для сотрудников</h1>
        <p className="login-description">
          Войдите с учётной записью, выданной администратором.
        </p>
        {message && <p className="session-message" role="status">{message}</p>}
        <form className="login-form" onSubmit={submit}>
          <label htmlFor="username">Логин</label>
          <input
            autoComplete="username"
            id="username"
            onChange={(event) => setUsername(event.target.value)}
            required
            value={username}
          />
          <label htmlFor="password">Пароль</label>
          <input
            autoComplete="current-password"
            id="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button login-submit" disabled={submitting} type="submit">
            {submitting ? "Проверяем…" : "Войти"}
            {!submitting && <ArrowRight size={17} />}
          </button>
        </form>
        <p className="login-footnote">Сеанс действует ограниченное время и хранится только в этой вкладке.</p>
      </section>
    </main>
  );
}

function OrderCard({
  order,
  role,
  busy,
  onAdvance,
  onCancel,
  onSelect,
}: {
  order: Order;
  role: StaffRole;
  busy: boolean;
  onAdvance: (order: Order, target: OrderStatus) => void;
  onCancel: (order: Order) => void;
  onSelect: (order: Order) => void;
}) {
  const action = nextStatus(order, role);
  return (
    <article className="order-card">
      <button className="order-card-main" onClick={() => onSelect(order)} type="button">
        <div className="order-card-heading">
          <span className="order-number">{order.order_number}</span>
          <span className={`status-pill status-${order.status.toLowerCase()}`}>
            {STATUS_LABELS[order.status]}
          </span>
        </div>
        <div className="order-meta">
          <span><Clock3 size={15} /> {formatTime(order.slot_start_time, true)}</span>
          <span>№ версии {order.version}</span>
        </div>
        <p className="order-items-preview">
          {order.items.map((item) => `${item.name_at_moment} × ${item.quantity}`).join(" · ")}
        </p>
      </button>
      <div className="order-card-bottom">
        <strong>{formatMoney(order.total_amount)}</strong>
        <div className="order-actions">
          {canCancel(order, role) && (
            <button
              className="text-button danger-text"
              disabled={busy}
              onClick={() => onCancel(order)}
              type="button"
            >
              Отменить
            </button>
          )}
          {action && (
            <button
              className="primary-button action-button"
              disabled={busy}
              onClick={() => onAdvance(order, action)}
              type="button"
            >
              {busy ? "Сохраняем…" : STATUS_LABELS[action]}
              {!busy && <ArrowRight size={15} />}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

function OrderDetails({ order, onClose }: { order: Order; onClose: () => void }) {
  return (
    <div className="dialog-backdrop" onClick={onClose} role="presentation">
      <section
        aria-labelledby="detail-title"
        aria-modal="true"
        className="detail-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">ЗАКАЗ · ВЕРСИЯ {order.version}</p>
            <h2 id="detail-title">{order.order_number}</h2>
          </div>
          <button aria-label="Закрыть детали" className="icon-button" onClick={onClose} type="button">×</button>
        </div>
        <p className="detail-slot">
          Выдача {formatTime(order.slot_start_time, true)}–{formatTime(order.slot_end_time)} МСК
        </p>
        <ul className="detail-items">
          {order.items.map((item) => (
            <li key={item.id}>
              <span>{item.name_at_moment}<small> × {item.quantity}</small></span>
              <strong>{formatMoney(item.price_at_moment * item.quantity)}</strong>
            </li>
          ))}
        </ul>
        <div className="detail-total"><span>Итого</span><strong>{formatMoney(order.total_amount)}</strong></div>
        <p className="detail-status">Статус: {STATUS_LABELS[order.status]}</p>
      </section>
    </div>
  );
}

export default function Home() {
  const [session, setSession] = useState<StaffSession | null>(null);
  const [booting, setBooting] = useState(true);
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const signOut = useCallback((reason = "") => {
    sessionStorage.removeItem(SESSION_KEY);
    setSession(null);
    setOrders([]);
    setSelected(null);
    setError(reason);
  }, []);

  const loadQueue = useCallback(async (activeSession: StaffSession, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      for (const status of queueStatuses(activeSession.user.role)) params.append("status", status);
      params.set("limit", "100");
      const result = await apiRequest<OrderPage>(`/orders/?${params.toString()}`, activeSession.token);
      setOrders(result.items);
      setTotal(result.total);
      setLastUpdated(new Date());
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
      } else if (caught instanceof ApiError && caught.status === 403) {
        signOut("Эта учётная запись больше не имеет доступа к рабочему месту.");
      } else {
        setError(messageFor(caught));
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [signOut]);

  useEffect(() => {
    let active = true;
    async function restore() {
      let restored = false;
      try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return;
        const stored = JSON.parse(raw) as Pick<StaffSession, "token" | "expiresAt">;
        if (!stored.token || stored.expiresAt <= Date.now()) {
          sessionStorage.removeItem(SESSION_KEY);
          return;
        }
        const user = await apiRequest<UserProfile>("/users/me", stored.token);
        if (active && isStaffRole(user.role)) {
          setSession({ ...stored, user });
          restored = true;
          return;
        }
      } catch {
        // Stale or invalid browser sessions return to the staff login form.
      } finally {
        if (active) {
          if (!restored) sessionStorage.removeItem(SESSION_KEY);
          setBooting(false);
        }
      }
    }
    void restore();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!session) return;
    const remaining = session.expiresAt - Date.now();
    if (remaining <= 0) {
      signOut("Срок входа истёк. Войдите снова.");
      return;
    }
    const timer = window.setTimeout(
      () => signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу."),
      remaining,
    );
    return () => window.clearTimeout(timer);
  }, [session, signOut]);

  useEffect(() => {
    if (!session) return;
    void loadQueue(session);
    const timer = window.setInterval(() => void loadQueue(session, true), 15_000);
    const onFocus = () => void loadQueue(session, true);
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [session, loadQueue]);

  const grouped = useMemo(() => ({
    active: orders.filter((order) => order.status !== "READY"),
    ready: orders.filter((order) => order.status === "READY"),
  }), [orders]);

  async function updateStatus(order: Order, status: OrderStatus) {
    if (!session || busyId) return;
    setBusyId(order.id);
    setNotice("");
    try {
      await apiRequest<Order>(`/orders/${order.id}/status`, session.token, {
        method: "PATCH",
        body: JSON.stringify({ status, expected_version: order.version }),
      });
      setNotice(`${order.order_number}: ${STATUS_LABELS[status].toLowerCase()}.`);
      await loadQueue(session, true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
      } else if (caught instanceof ApiError && caught.status === 409) {
        await loadQueue(session, true);
        setNotice("Заказ уже изменился. Очередь обновлена — проверьте текущий статус и повторите действие.");
      } else {
        setError(messageFor(caught));
      }
    } finally {
      setBusyId(null);
    }
  }

  async function cancelOrder(order: Order) {
    if (!session || busyId) return;
    if (!window.confirm(`Отменить ${order.order_number}?`)) return;
    setBusyId(order.id);
    setNotice("");
    try {
      await apiRequest<Order>(`/orders/${order.id}/cancel`, session.token, {
        method: "POST",
        body: JSON.stringify({ expected_version: order.version }),
      });
      setNotice(`${order.order_number} отменён.`);
      await loadQueue(session, true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
      } else if (caught instanceof ApiError && caught.status === 409) {
        await loadQueue(session, true);
        setNotice("Статус заказа изменился. Очередь обновлена — проверьте заказ перед повтором.");
      } else {
        setError(messageFor(caught));
      }
    } finally {
      setBusyId(null);
    }
  }

  function login(newSession: StaffSession) {
    setError("");
    setNotice("");
    setSession(newSession);
  }

  if (booting) {
    return <main className="loading-screen" aria-live="polite">Проверяем сессию…</main>;
  }
  if (!session) return <LoginPanel message={error} onLogin={login} />;

  const isCook = session.user.role === "COOK";
  const sections = isCook
    ? [{ title: "В работе", items: grouped.active }]
    : session.user.role === "CASHIER"
      ? [{ title: "К выдаче", items: grouped.ready }]
      : [
          { title: "Приготовление", items: grouped.active },
          { title: "К выдаче", items: grouped.ready },
        ];

  return (
    <main className="kitchen-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark"><Utensils size={19} strokeWidth={2.2} /></div>
          <div><p className="eyebrow">МАИ · СТОЛОВАЯ</p><strong>Рабочее место кухни</strong></div>
        </div>
        <div className="account-area">
          <div className="account-copy">
            <strong>{session.user.full_name}</strong>
            <span>{ROLE_LABELS[session.user.role]}</span>
          </div>
          <button className="icon-button logout-button" onClick={() => signOut()} title="Выйти" type="button">
            <LogOut size={17} /><span>Выйти</span>
          </button>
        </div>
      </header>

      <section className="queue-header">
        <div>
          <p className="eyebrow">ОЧЕРЕДЬ ЗАКАЗОВ</p>
          <h1>{isCook ? "Приготовление" : session.user.role === "CASHIER" ? "Выдача заказов" : "Смена кухни"}</h1>
          <p className="queue-subtitle">
            {session.user.role === "CASHIER"
              ? "Подтвердите выдачу после передачи заказа гостю."
              : "Обновления приходят автоматически. Перед действием сверяйте версию заказа."}
          </p>
        </div>
        <div className="queue-tools">
          <div className="connection-state"><span className="live-dot" /> Синхронизация каждые 15 сек.</div>
          <button className="secondary-button" disabled={loading} onClick={() => void loadQueue(session)} type="button">
            <RefreshCw className={loading ? "spin" : ""} size={16} /> Обновить
          </button>
        </div>
      </section>

      {error && (
        <div className="alert alert-error" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
          <button className="text-button" onClick={() => void loadQueue(session)} type="button">Повторить</button>
        </div>
      )}
      {notice && <div className="alert alert-success" role="status"><Check size={18} /><span>{notice}</span></div>}

      <div className="queue-summary">
        <div><span>Активных заказов</span><strong>{total}</strong></div>
        <div><span>Обновлено</span><strong>{lastUpdated ? formatTime(lastUpdated.toISOString()) : "—"}</strong></div>
      </div>

      {loading && orders.length === 0 ? (
        <div className="queue-state"><span className="spinner" /><strong>Загружаем очередь…</strong></div>
      ) : error && orders.length === 0 ? (
        <div className="queue-state" role="status">
          <div className="empty-icon"><AlertCircle size={23} /></div>
          <strong>Не удалось загрузить очередь</strong>
          <span>Проверьте подключение и попробуйте ещё раз.</span>
          <button className="secondary-button" onClick={() => void loadQueue(session)} type="button">
            <RefreshCw size={15} /> Повторить
          </button>
        </div>
      ) : !error && orders.length === 0 ? (
        <div className="queue-state empty-state">
          <div className="empty-icon"><ChefHat size={25} /></div>
          <strong>Очередь пока пуста</strong>
          <span>Новые заказы появятся здесь автоматически.</span>
        </div>
      ) : (
        <div className="queue-sections">
          {sections.map((section) => (
            <section className="queue-section" key={section.title}>
              <div className="section-heading">
                <h2>{section.title}</h2><span>{section.items.length}</span>
              </div>
              {section.items.length === 0 ? (
                <div className="section-empty">Нет заказов в этом разделе.</div>
              ) : (
                <div className="order-grid">
                  {section.items.map((order) => (
                    <OrderCard
                      busy={busyId === order.id}
                      key={order.id}
                      onAdvance={updateStatus}
                      onCancel={cancelOrder}
                      onSelect={setSelected}
                      order={order}
                      role={session.user.role}
                    />
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}

      <footer className="kitchen-footer"><span>Рабочее место кухни · МСК</span><span>Для помощи обратитесь к администратору</span></footer>
      {selected && <OrderDetails onClose={() => setSelected(null)} order={selected} />}
    </main>
  );
}
