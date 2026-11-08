"use client";

import {
  AlertCircle,
  ArrowRight,
  Check,
  ChefHat,
  LogOut,
  RefreshCw,
  ClipboardList,
  PackageCheck,
  Settings,
  Ticket,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { CancelDialog } from "../components/cancel-dialog";
import { AdminPanel } from "../components/admin-panel";
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
} from "../lib/kitchen";

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
      const result = await apiRequest<LoginResponse>(
        "/users/auth/staff",
        undefined,
        {
          method: "POST",
          body: JSON.stringify({ username, password }),
        },
      );
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
        <div className="brand-mark">
          <Wing />
        </div>
        <p className="eyebrow">МАИ · СТОЛОВАЯ</p>
        <h1 id="login-title">Вход для сотрудников</h1>
        <p className="login-description">
          Войдите с учётной записью, выданной администратором.
        </p>
        {message && (
          <p className="session-message" role="status">
            {message}
          </p>
        )}
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
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary-button login-submit"
            disabled={submitting}
            type="submit"
          >
            {submitting ? "Проверяем…" : "Войти"}
            {!submitting && <ArrowRight size={17} />}
          </button>
        </form>
        <p className="login-footnote">
          Сеанс действует ограниченное время и хранится только в этой вкладке.
        </p>
      </section>
    </main>
  );
}

export default function Home() {
  const activeToken = useRef<string | null>(null);
  const queueRequest = useRef(0);
  const mutation = useRef<symbol | null>(null);
  const [cancelCandidate, setCancelCandidate] = useState<Order | null>(null);
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
  const [activeView, setActiveView] = useState<
    "queue" | "kitchen" | "pickup" | "admin"
  >("queue");

  const signOut = useCallback((reason = "") => {
    activeToken.current = null;
    queueRequest.current += 1;
    mutation.current = null;
    sessionStorage.removeItem(SESSION_KEY);
    setSession(null);
    setCancelCandidate(null);
    setBusyId(null);
    setTotal(0);
    setLastUpdated(null);
    setNotice("");
    setOrders([]);
    setSelected(null);
    setError(reason);
  }, []);
  const handleAdminUnauthorized = useCallback(() => {
    if (activeToken.current === session?.token) {
      signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
    }
  }, [signOut, session?.token]);

  const loadQueue = useCallback(
    async (activeSession: StaffSession, quiet = false) => {
      if (activeToken.current !== activeSession.token) return;
      const requestId = ++queueRequest.current;
      const isCurrent = () =>
        activeToken.current === activeSession.token &&
        queueRequest.current === requestId;
      if (!quiet) setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams();
        for (const status of queueStatuses(activeSession.user.role))
          params.append("status", status);
        params.set("limit", "100");
        const result = await apiRequest<OrderPage>(
          `/orders/?${params.toString()}`,
          activeSession.token,
        );
        if (!isCurrent()) return;
        setOrders(result.items);
        setTotal(result.total);
        setLastUpdated(new Date());
      } catch (caught) {
        if (!isCurrent()) return;
        if (caught instanceof ApiError && caught.status === 401) {
          signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
        } else if (caught instanceof ApiError && caught.status === 403) {
          signOut(
            "Эта учётная запись больше не имеет доступа к рабочему месту.",
          );
        } else {
          setError(messageFor(caught));
        }
      } finally {
        if (isCurrent()) setLoading(false);
      }
    },
    [signOut],
  );

  useEffect(() => {
    let active = true;
    async function restore() {
      let restored = false;
      try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return;
        const stored = JSON.parse(raw) as Pick<
          StaffSession,
          "token" | "expiresAt"
        >;
        if (!stored.token || stored.expiresAt <= Date.now()) {
          sessionStorage.removeItem(SESSION_KEY);
          return;
        }
        const user = await apiRequest<UserProfile>("/users/me", stored.token);
        if (active && isStaffRole(user.role)) {
          activeToken.current = stored.token;
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
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    const remaining = session.expiresAt - Date.now();
    if (remaining <= 0) {
      signOut("Срок входа истёк. Войдите снова.");
      return;
    }
    const timer = window.setTimeout(
      () =>
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу."),
      remaining,
    );
    return () => window.clearTimeout(timer);
  }, [session, signOut]);

  useEffect(() => {
    if (!session) return;
    void loadQueue(session);
    const timer = window.setInterval(
      () => void loadQueue(session, true),
      15_000,
    );
    const onFocus = () => void loadQueue(session, true);
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [session, loadQueue]);

  const grouped = useMemo(
    () => ({
      active: orders.filter((order) => order.status !== "READY"),
      ready: orders.filter((order) => order.status === "READY"),
    }),
    [orders],
  );

  async function updateStatus(order: Order, status: OrderStatus) {
    if (!session || mutation.current) return;
    const operation = Symbol("staff-order-action");
    mutation.current = operation;
    const token = session.token;
    const isCurrent = () => activeToken.current === token;
    setCancelCandidate(null);
    setBusyId(order.id);
    setNotice("");
    try {
      await apiRequest<Order>(`/orders/${order.id}/status`, session.token, {
        method: "PATCH",
        body: JSON.stringify({ status, expected_version: order.version }),
      });
      if (!isCurrent()) return;
      setNotice(
        `${order.order_number}: ${STATUS_LABELS[status].toLowerCase()}.`,
      );
      await loadQueue(session, true);
    } catch (caught) {
      if (!isCurrent()) return;
      if (caught instanceof ApiError && caught.status === 401) {
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
      } else if (caught instanceof ApiError && caught.status === 409) {
        await loadQueue(session, true);
        if (!isCurrent()) return;
        setNotice(
          "Заказ уже изменился. Очередь обновлена — проверьте текущий статус и повторите действие.",
        );
      } else {
        setError(messageFor(caught));
      }
    } finally {
      if (mutation.current === operation) mutation.current = null;
      if (isCurrent()) setBusyId(null);
    }
  }

  async function cancelOrder(order: Order) {
    if (!session || mutation.current) return;
    const operation = Symbol("staff-order-action");
    mutation.current = operation;
    const token = session.token;
    const isCurrent = () => activeToken.current === token;
    setCancelCandidate(null);
    setBusyId(order.id);
    setNotice("");
    try {
      await apiRequest<Order>(`/orders/${order.id}/cancel`, session.token, {
        method: "POST",
        body: JSON.stringify({ expected_version: order.version }),
      });
      if (!isCurrent()) return;
      setNotice(`${order.order_number} отменён.`);
      await loadQueue(session, true);
    } catch (caught) {
      if (!isCurrent()) return;
      if (caught instanceof ApiError && caught.status === 401) {
        signOut("Срок входа истёк. Войдите снова, чтобы продолжить работу.");
      } else if (caught instanceof ApiError && caught.status === 409) {
        await loadQueue(session, true);
        if (!isCurrent()) return;
        setNotice(
          "Статус заказа изменился. Очередь обновлена — проверьте заказ перед повтором.",
        );
      } else {
        setError(messageFor(caught));
      }
    } finally {
      if (mutation.current === operation) mutation.current = null;
      if (isCurrent()) setBusyId(null);
    }
  }

  function login(newSession: StaffSession) {
    activeToken.current = newSession.token;
    queueRequest.current += 1;
    setActiveView("queue");
    setError("");
    setNotice("");
    setSession(newSession);
  }

  if (booting) {
    return (
      <main className="loading-screen" aria-live="polite">
        Проверяем сессию…
      </main>
    );
  }
  if (!session) return <LoginPanel message={error} onLogin={login} />;

  const isCook = session.user.role === "COOK";
  const isCashier = session.user.role === "CASHIER";
  const isAdmin = session.user.role === "ADMIN";
  const shown =
    activeView === "pickup" || isCashier
      ? grouped.ready
      : activeView === "kitchen" || isCook
        ? grouped.active
        : orders;
  const focused = shown.find((order) => order.id === selected?.id) ?? shown[0];
  const action = focused ? nextStatus(focused, session.user.role) : null;
  const heading =
    activeView === "admin"
      ? "Меню и расписание"
      : activeView === "pickup" || isCashier
        ? "Проверка и выдача"
        : activeView === "kitchen" || isCook
          ? "Приготовление заказа"
          : "Заказы на сегодня";

  return (
    <main className="kitchen-shell">
      <aside className="staff-sidebar">
        <div className="staff-brand">
          <Wing />
          <strong>МАИ еда</strong>
          <span>
            СТОЛОВАЯ МАИ
            <br />
            РАБОЧЕЕ МЕСТО
          </span>
        </div>
        <nav aria-label="Разделы рабочего места">
          {isAdmin && (
            <button
              aria-current={activeView === "queue" ? "page" : undefined}
              onClick={() => setActiveView("queue")}
            >
              <Ticket size={21} />
              Заказы
            </button>
          )}
          {!isCashier && (
            <button
              aria-current={
                activeView === "kitchen" || isCook ? "page" : undefined
              }
              onClick={() => setActiveView("kitchen")}
            >
              <ChefHat size={21} />
              Кухня
            </button>
          )}
          {!isCook && (
            <button
              aria-current={
                activeView === "pickup" || isCashier ? "page" : undefined
              }
              onClick={() => setActiveView("pickup")}
            >
              <PackageCheck size={21} />
              Выдача
            </button>
          )}
          {isAdmin && (
            <button
              aria-current={activeView === "admin" ? "page" : undefined}
              onClick={() => setActiveView("admin")}
            >
              <Settings size={21} />
              Меню и слоты
            </button>
          )}
        </nav>
        <svg
          className="sidebar-aircraft"
          viewBox="0 0 140 120"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M8 84L130 20L96 92L40 114L8 84ZM40 114L48 62"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
        <div className="staff-account">
          <strong>{session.user.full_name}</strong>
          <span>{ROLE_LABELS[session.user.role]}</span>
          <button onClick={() => signOut()}>
            <LogOut size={16} />
            Выйти
          </button>
        </div>
      </aside>
      <div className="staff-content">
        <header className="workspace-heading">
          <div>
            <h1>{heading}</h1>
            <p>Столовая МАИ · {ROLE_LABELS[session.user.role]}</p>
          </div>
          <div className="workspace-clock">
            {lastUpdated ? formatTime(lastUpdated.toISOString()) : "—"} / МСК
            <button
              className="text-button"
              disabled={loading}
              onClick={() => void loadQueue(session)}
              aria-label="Обновить очередь"
            >
              <RefreshCw size={16} className={loading ? "spin" : ""} />
            </button>
          </div>
        </header>
        {isAdmin && activeView === "admin" ? (
          <AdminPanel
            onUnauthorized={handleAdminUnauthorized}
            session={session}
          />
        ) : (
          <>
            {error && (
              <div className="alert alert-error" role="alert">
                <AlertCircle size={18} />
                <span>{error}</span>
                <button
                  className="text-button"
                  onClick={() => void loadQueue(session)}
                >
                  Повторить
                </button>
              </div>
            )}
            {notice && (
              <div className="alert alert-success" role="status">
                <Check size={18} />
                <span>{notice}</span>
              </div>
            )}
            <section className="shift-summary" aria-label="Сводка смены">
              <strong>Заказов в очереди: {total}</strong>
              <span>Готовы к выдаче: {grouped.ready.length}</span>
              <small>Синхронизация каждые 15 сек.</small>
            </section>
            <div className="dispatch-layout">
              <section className="dispatch-list" aria-label="Очередь заказов">
                <h2>Ближайшие заказы</h2>
                <p className="dispatch-list-caption">ЗАКАЗ / ВРЕМЯ / СТАТУС</p>
                {loading && orders.length === 0 && (
                  <p role="status">Загружаем очередь…</p>
                )}
                {!loading && shown.length === 0 && (
                  <p className="section-empty">
                    {error
                      ? "Очередь недоступна"
                      : "Нет заказов в этом разделе."}
                  </p>
                )}
                {shown.map((order) => (
                  <button
                    key={order.id}
                    className="dispatch-row"
                    aria-pressed={focused?.id === order.id}
                    onClick={() => setSelected(order)}
                  >
                    <strong>{order.order_number}</strong>
                    <span>
                      {formatTime(order.slot_start_time, true)}–
                      {formatTime(order.slot_end_time)}
                    </span>
                    <small
                      className={`dispatch-status status-${order.status.toLowerCase()}`}
                    >
                      {STATUS_LABELS[order.status]}
                    </small>
                  </button>
                ))}
                {total > orders.length && (
                  <p className="queue-limit">
                    Показано {orders.length} из {total} заказов.
                  </p>
                )}
              </section>
              <section className="working-ticket" aria-label="Рабочая карточка">
                {focused ? (
                  <>
                    <h2>{focused.order_number}</h2>
                    <span
                      className={`status-pill status-${focused.status.toLowerCase()}`}
                    >
                      {STATUS_LABELS[focused.status]}
                    </span>
                    <h3>
                      Получение {formatTime(focused.slot_start_time)}–
                      {formatTime(focused.slot_end_time)}
                    </h3>
                    <p className="working-ticket-date">
                      {formatTime(focused.slot_start_time, true)} МСК · версия{" "}
                      {focused.version}
                    </p>
                    <ul className="working-ticket-items">
                      {focused.items.map((item) => (
                        <li key={item.id}>
                          <span>
                            {item.name_at_moment} × {item.quantity}
                          </span>
                          <strong>
                            {formatMoney(item.price_at_moment * item.quantity)}
                          </strong>
                        </li>
                      ))}
                    </ul>
                    <p className="working-ticket-total">
                      Итого {formatMoney(focused.total_amount)}
                    </p>
                    <p className="staff-payment">
                      {focused.payment_status === "DEMO_PAID"
                        ? "Оплачено с демонстрационного баланса"
                        : focused.payment_status === "DEMO_REFUNDED"
                          ? "Демонстрационные средства возвращены"
                          : focused.payment_status === "NOT_REQUIRED"
                            ? "Оплата не требуется"
                            : "Данные об оплате не получены"}
                    </p>
                    <div className="working-guidance">
                      <ClipboardList size={22} />
                      <div>
                        <strong>
                          {focused.status === "READY"
                            ? "Проверьте заказ перед выдачей"
                            : "Следующее действие"}
                        </strong>
                        <p>
                          {focused.status === "READY"
                            ? "Сверьте номер заказа и состав с гостем."
                            : focused.status === "PREPARING"
                              ? "Отметьте готовность после приготовления всех блюд."
                              : "Начните приготовление выбранного заказа."}
                        </p>
                      </div>
                    </div>
                    <div className="working-actions">
                      {action && (
                        <button
                          className="primary-button"
                          disabled={busyId !== null}
                          onClick={() => void updateStatus(focused, action)}
                        >
                          {busyId === focused.id
                            ? "Сохраняем…"
                            : action === "PREPARING"
                              ? "Начать приготовление"
                              : action === "READY"
                                ? "Готов к выдаче"
                                : "Подтвердить выдачу"}
                          <ArrowRight size={18} />
                        </button>
                      )}
                      {canCancel(focused, session.user.role) && (
                        <button
                          className="text-button danger-text"
                          disabled={busyId !== null}
                          onClick={() => setCancelCandidate(focused)}
                        >
                          Отменить заказ
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="working-empty">
                    <ChefHat size={40} />
                    <h2>Всё по плану</h2>
                    <p>
                      Выберите заказ из очереди. Здесь появятся состав и
                      следующее действие.
                    </p>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
      </div>
      {cancelCandidate && (
        <CancelDialog
          number={cancelCandidate.order_number}
          busy={busyId !== null}
          onDismiss={() => setCancelCandidate(null)}
          onConfirm={() => void cancelOrder(cancelCandidate)}
        />
      )}
    </main>
  );
}

function Wing() {
  return (
    <svg
      className="wing-mark"
      aria-hidden="true"
      width="26"
      height="26"
      viewBox="0 0 26 26"
    >
      <path
        fill="currentColor"
        d="M3 6H22L17 10H1L3 6ZM5 12H17L12 16H3L5 12ZM7 18H12L8 21H5L7 18Z"
      />
    </svg>
  );
}
