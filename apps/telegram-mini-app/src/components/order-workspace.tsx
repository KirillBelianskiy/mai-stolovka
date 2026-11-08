"use client";

import { useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowRight,
  RefreshCw,
  Ticket,
  Clock3,
  AlertCircle,
} from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import {
  createIntent,
  persistIntent,
  readIntent,
  removeIntent,
  type CheckoutIntent,
} from "@/lib/checkout";
import { money, type CartLine } from "@/lib/menu";
import {
  canCancel,
  cancelOrder,
  createOrder,
  formatSlot,
  loadOrder,
  loadOrders,
  loadSlots,
  loadWallet,
  paymentLabel,
  orderFailure,
  OrderApiError,
  STATUS_LABELS,
  type Order,
} from "@/lib/orders";

type CheckoutProps = {
  cart: CartLine[];
  total: number | null;
  onComplete: (intent: CheckoutIntent) => void;
};
const knownRejections = new Set([
  "PRICE_CHANGED",
  "SLOT_FULL",
  "SLOT_CLOSED",
  "SLOT_NOT_FOUND",
  "TOTAL_TOO_LARGE",
  "INSUFFICIENT_FUNDS",
  "MENU_ITEM_NOT_FOUND",
  "MENU_ITEM_UNAVAILABLE",
  "DISH_UNAVAILABLE",
  "ITEM_UNAVAILABLE",
]);

export function CheckoutPanel(props: CheckoutProps) {
  const auth = useAuth();
  if (auth.status !== "authenticated" || !auth.credentials)
    return (
      <div className="checkout-login">
        <p>Войдите, чтобы выбрать время и оформить заказ.</p>
        <a href="#profile">
          Открыть профиль <ArrowRight size={15} />
        </a>
      </div>
    );
  if (auth.credentials.user.role !== "CLIENT")
    return <p className="inline-note">Для заказа нужен аккаунт посетителя.</p>;
  return (
    <CheckoutSession
      key={auth.credentials.user.id}
      accountId={auth.credentials.user.id}
      {...props}
    />
  );
}
function CheckoutSession({
  accountId,
  cart,
  total,
  onComplete,
}: CheckoutProps & { accountId: string }) {
  const auth = useAuth(),
    client = useQueryClient();
  const [intent, setIntent] = useState<CheckoutIntent | null>(null),
    [ready, setReady] = useState(false),
    [storageError, setStorageError] = useState(false);
  const [slotId, setSlotId] = useState(""),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  const [price, setPrice] = useState<{
      total: number;
      cart: string;
      slot: string;
    } | null>(null),
    [ticket, setTicket] = useState<string | null>(null),
    [confirmed, setConfirmed] = useState("");
  const [clearWarning, setClearWarning] = useState(false);
  const lock = useRef(false),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    try {
      setIntent(readIntent(sessionStorage));
    } catch {
      setStorageError(true);
    }
    setReady(true);
    return () => {
      mounted.current = false;
    };
  }, []);
  const wallet = useQuery({
    queryKey: ["own-orders", accountId, "wallet"],
    queryFn: ({ signal }) => auth.withAccount(accountId, (t) => loadWallet(accountId, t, signal)),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  const slots = useInfiniteQuery({
    queryKey: ["own-orders", accountId, "slots"],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      auth.withAccount(accountId, (t) => loadSlots(t, pageParam, signal)),
    getNextPageParam: (last, pages) =>
      last.length === 50 ? pages.length * 50 : undefined,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  const choices = [
    ...new Map(slots.data?.pages.flat().map((s) => [s.id, s]) ?? []).values(),
  ];
  const selected = choices.find((s) => s.id === slotId);
  const cartStamp = JSON.stringify(
    cart
      .map((line) => ({ menu_item_id: line.id, quantity: line.quantity }))
      .sort((a, b) => a.menu_item_id.localeCompare(b.menu_item_id)),
  );
  const priceApplicable =
    price && price.cart === cartStamp && price.slot === slotId;
  const valid =
    ready &&
    !storageError &&
    !intent &&
    cart.length > 0 &&
    total !== null &&
    selected &&
    selected.remaining_capacity > 0 &&
    Date.parse(selected.start_time) > Date.now() &&
    !auth.busy;
  const paymentReady = wallet.isSuccess && !wallet.isFetching;
  async function send(saved: CheckoutIntent, recovering: boolean) {
    if (lock.current || auth.busy) return;
    lock.current = true;
    setBusy(true);
    setFailure("");
    setConfirmed("");
    let attempted = false;
    try {
      if (saved.account_id !== accountId)
        throw new Error("Wrong account intent");
      persistIntent(sessionStorage, saved);
      setIntent(saved);
      setStorageError(false);
      attempted = true;
      const result = await auth.withAccount(accountId, (t) =>
        createOrder(saved, t),
      );
      if (!mounted.current) return;
      setTicket(result.id);
      setConfirmed(`Запрос подтверждён. Заказ ${result.order_number}.`);
      void client.invalidateQueries({ queryKey: ["own-orders", accountId] });
      try {
        removeIntent(sessionStorage, saved.key);
      } catch {
        setStorageError(true);
        setFailure(
          "Заказ подтверждён, но ключ восстановления не удалось удалить. Новый заказ заблокирован; сначала проверьте талон и историю.",
        );
        return;
      }
      setIntent(null);
      setPrice(null);
      onComplete(saved);
    } catch (error) {
      if (!mounted.current) return;
      if (!attempted) {
        setStorageError(true);
        setFailure(
          "Не удалось надёжно сохранить запрос. Заказ не отправлен. Проверьте доступ к хранилищу вкладки.",
        );
        return;
      }
      const rejection =
        !recovering &&
        error instanceof OrderApiError &&
        error.code &&
        knownRejections.has(error.code);
      if (rejection) {
        try {
          removeIntent(sessionStorage, saved.key);
          setIntent(null);
          if (error.code === "PRICE_CHANGED" && error.totalAmount !== null)
            setPrice({
              total: error.totalAmount,
              cart: JSON.stringify(saved.body.items),
              slot: saved.body.slot_id,
            });
        } catch {
          setStorageError(true);
        }
      }
      setFailure(orderFailure(error));
      void slots.refetch();
    } finally {
      lock.current = false;
      if (mounted.current) {
        setBusy(false);
        void client.invalidateQueries({ queryKey: ["own-orders", accountId, "wallet"] });
      }
    }
  }
  function start(amount: number) {
    if (!valid || !paymentReady || lock.current) return;
    try {
      const existing = readIntent(sessionStorage);
      if (existing) {
        setIntent(existing);
        return;
      }
      void send(createIntent(accountId, cart, slotId, amount), false);
    } catch {
      setStorageError(true);
      setFailure(
        "Сохранённые данные требуют проверки. Новый запрос не отправлен.",
      );
    }
  }
  function clear() {
    if (lock.current) return;
    try {
      removeIntent(sessionStorage);
      setIntent(null);
      setStorageError(false);
      setFailure("");
      setPrice(null);
      setClearWarning(false);
    } catch {
      setStorageError(true);
      setFailure("Не удалось очистить данные. Новый заказ заблокирован.");
    }
  }
  return (
    <section className="checkout-section" aria-labelledby="checkout-heading">
      <h3 id="checkout-heading">
        <Clock3 size={18} aria-hidden="true" /> Время выдачи
      </h3>
      <section className="demo-wallet" aria-label="Демонстрационный баланс">
        <div className="wallet-heading">
          <strong>Демобаланс</strong>
          <button className="text-button" disabled={wallet.isFetching || busy || auth.busy}
            onClick={() => void wallet.refetch()}>Обновить демобаланс</button>
        </div>
        {wallet.isPending ? <p role="status">Проверяем демобаланс…</p> : null}
        {wallet.isError ? <p role="alert">Не удалось обновить демобаланс. Данные могут быть устаревшими. Обновите баланс перед новым заказом.</p> : null}
        {wallet.data && <>
          <p className="wallet-amount">{money(wallet.data.balance)}</p>
          <p>{wallet.data.checkout_payment_enabled
            ? "При оформлении сервер спишет демосредства. Итог и доступный баланс проверяются заново."
            : "Демооплата выключена. Для нового заказа оплата не требуется."}</p>
          {wallet.data.checkout_payment_enabled && total !== null && wallet.data.balance < (priceApplicable ? price.total : total) &&
            <p className="wallet-shortfall">По последним данным средств недостаточно. После пополнения обновите баланс.</p>}
        </>}
        <p className="order-smallprint">Это учебные средства, не реальные деньги. Пополнение выполняет администратор через API/Swagger. Баланс — по последнему обновлению.</p>
      </section>
      {!ready ? (
        <p role="status">Проверяем незавершённые запросы…</p>
      ) : storageError ? (
        <div className="checkout-warning" role="alert">
          <p>
            Хранилище вкладки недоступно или сохранённый запрос повреждён.
            Оформление заблокировано.
          </p>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => setClearWarning(true)}
          >
            Очистить данные с предупреждением
          </button>
        </div>
      ) : intent ? (
        <div className="checkout-warning" role="status">
          <p>
            <strong>
              {intent.account_id === accountId
                ? "Есть незавершённый запрос"
                : "Есть запрос другого аккаунта"}
            </strong>
          </p>
          {intent.account_id === accountId ? (
            <>
              <p>
                Результат может быть уже сохранён. Повторяем исходный заказ на{" "}
                {money(intent.body.expected_total_amount)}, даже если корзина
                изменилась.
              </p>
              <button
                className="primary-button"
                disabled={busy || auth.busy}
                onClick={() => void send(intent, true)}
              >
                {busy ? "Проверяем результат…" : "Восстановить исходный заказ"}
              </button>
            </>
          ) : (
            <p>
              Вернитесь в исходный аккаунт. Этот запрос не будет отправлен от
              вашего имени.
            </p>
          )}
          <a className="text-button" href="#orders">
            Сначала проверить историю
          </a>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => setClearWarning(true)}
          >
            Очистить данные с предупреждением
          </button>
        </div>
      ) : (
        <>
          <label htmlFor="checkout-slot" className="slot-label">
            Когда заберёте обед · МСК
          </label>
          <select
            id="checkout-slot"
            value={slotId}
            onChange={(e) => {
              setSlotId(e.target.value);
              setPrice(null);
            }}
            disabled={busy || auth.busy || slots.isPending}
          >
            <option value="">Выберите время</option>
            {choices.map((slot) => (
              <option
                key={slot.id}
                value={slot.id}
                disabled={
                  slot.remaining_capacity <= 0 ||
                  Date.parse(slot.start_time) <= Date.now()
                }
              >
                {formatSlot(slot.start_time, slot.end_time)} ·{" "}
                {slot.remaining_capacity > 0
                  ? `мест: ${slot.remaining_capacity}`
                  : "мест нет"}
              </option>
            ))}
          </select>
          {slots.isPending && <p role="status">Загружаем время выдачи…</p>}
          {slots.isError && (
            <p role="alert">
              Не удалось обновить время.{" "}
              <button
                className="text-button"
                onClick={() => void slots.refetch()}
              >
                Повторить загрузку
              </button>
            </p>
          )}
          {!slots.isPending && !slots.isError && choices.length === 0 && (
            <p>Пока нет доступного времени. Проверьте позже.</p>
          )}
          <div className="slot-actions">
            <button
              className="text-button"
              disabled={slots.isFetching || busy}
              onClick={() => void slots.refetch()}
            >
              Обновить время
            </button>
            {slots.hasNextPage && (
              <button
                className="text-button"
                disabled={slots.isFetchingNextPage || busy}
                onClick={() => void slots.fetchNextPage()}
              >
                Ещё время
              </button>
            )}
          </div>
          {priceApplicable ? (
            <div className="price-confirmation" role="alert">
              <p>
                Новая сумма по данным столовой:{" "}
                <strong>{money(price.total)}</strong>. Подтвердите её отдельно.
              </p>
              <button
                className="primary-button"
                disabled={!valid || !paymentReady || busy}
                onClick={() => start(price.total)}
              >
                Подтвердить новую сумму {money(price.total)}
              </button>
            </div>
          ) : (
            <button
              className="primary-button checkout-submit"
              disabled={!valid || !paymentReady || busy}
              onClick={() => total !== null && start(total)}
            >
              {busy
                ? "Подтверждаем заказ…"
                : cart.length === 0
                  ? "Добавьте блюда из меню"
                  : `Заказать${total !== null ? ` за ${money(total)}` : ""}`}
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          )}
        </>
      )}
      {clearWarning && (
        <div
          className="checkout-warning"
          role="alertdialog"
          aria-label="Предупреждение об очистке запроса"
        >
          <p>
            Заказ мог быть создан. Сначала проверьте историю. Очистка удалит
            ключ восстановления: повторное оформление может создать ещё один
            заказ.
          </p>
          <button
            className="text-button"
            disabled={busy}
            autoFocus
            onClick={() => setClearWarning(false)}
          >
            Вернуться к запросу
          </button>
          <button className="text-button" disabled={busy} onClick={clear}>
            Удалить ключ восстановления
          </button>
        </div>
      )}
      <p className="checkout-privacy">
        Запрос сохраняется только в этой вкладке, без данных входа. Закрытие
        вкладки или очистка данных может лишить восстановления. История заказов
        хранится у столовой.
      </p>
      {failure && (
        <p role="alert" className="order-feedback">
          {failure}
          {intent?.account_id === accountId &&
            " Не создавайте новый заказ, пока не проверите исходный запрос."}
        </p>
      )}
      {confirmed && (
        <p role="status" className="order-confirmed">
          {confirmed}
        </p>
      )}
      {ticket && <OrderTicket accountId={accountId} id={ticket} />}
    </section>
  );
}

export function OrdersPanel() {
  const auth = useAuth(),
    client = useQueryClient();
  const id =
    auth.status === "authenticated" && auth.credentials?.user.role === "CLIENT"
      ? auth.credentials.user.id
      : null;
  useEffect(
    () => () => {
      if (id) {
        void client.cancelQueries({ queryKey: ["own-orders", id] });
        client.removeQueries({ queryKey: ["own-orders", id] });
      }
    },
    [client, id],
  );
  return (
    <section
      className="orders-section"
      id="orders"
      aria-labelledby="orders-heading"
    >
      <div className="profile-heading">
        <div>
          <p className="eyebrow">Ваши заказы</p>
          <h2 id="orders-heading">Обед по плану</h2>
        </div>
        <Ticket size={25} aria-hidden="true" />
      </div>
      {id ? (
        <OrderHistory key={id} accountId={id} />
      ) : (
        <p>
          История доступна после <a href="#profile">входа в аккаунт</a>.
        </p>
      )}
    </section>
  );
}
function OrderHistory({ accountId }: { accountId: string }) {
  const auth = useAuth();
  const [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["own-orders", accountId, "history", offset],
    queryFn: ({ signal }) =>
      auth.withAccount(accountId, (t) =>
        loadOrders(accountId, t, offset, signal),
      ),
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  return (
    <>
      <div className="orders-toolbar">
        <p>
          По последнему обновлению. При возвращении в приложение сверяем статус.
        </p>
        <button
          className="text-button"
          disabled={history.isFetching}
          onClick={() => void history.refetch()}
        >
          <RefreshCw size={15} /> Обновить историю
        </button>
      </div>
      {history.isPending ? (
        <p role="status">Загружаем заказы…</p>
      ) : history.isError ? (
        <p role="alert">
          {orderFailure(history.error)} Показанные данные могут устареть.
        </p>
      ) : null}
      {history.data?.items.length === 0 && (
        <p className="orders-empty">
          Здесь появятся ваши заказы и талоны на выдачу.
        </p>
      )}
      <div className="order-list">
        {history.data?.items.map((order) => (
          <button
            className={`order-row ${selected === order.id ? "selected" : ""}`}
            key={order.id}
            onClick={() => setSelected(order.id)}
          >
            <span>
              <strong>{order.order_number}</strong>
              <span>
                {formatSlot(order.slot_start_time, order.slot_end_time)}
              </span>
            </span>
            <span>
              <span
                className={`order-status status-${order.status.toLowerCase()}`}
              >
                {STATUS_LABELS[order.status]}
              </span>
              <strong>{money(order.total_amount)}</strong>
              <span className="payment-evidence">{paymentLabel(order.payment_status)}</span>
            </span>
          </button>
        ))}
      </div>
      {history.data && (
        <div className="order-pagination">
          <button
            className="text-button"
            disabled={offset === 0 || history.isFetching}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            Назад
          </button>
          <span>
            Страница {offset / 10 + 1} · всего {history.data.total}
          </span>
          <button
            className="text-button"
            disabled={
              offset + history.data.items.length >= history.data.total ||
              history.isFetching
            }
            onClick={() => setOffset(offset + 10)}
          >
            Дальше
          </button>
        </div>
      )}
      <p className="order-smallprint">
        История может меняться между страницами. Время — московское, МСК.
      </p>
      {selected && (
        <OrderTicket key={selected} accountId={accountId} id={selected} />
      )}
    </>
  );
}
function OrderTicket({ accountId, id }: { accountId: string; id: string }) {
  const auth = useAuth(),
    client = useQueryClient();
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const lock = useRef(false),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const detail = useQuery({
    queryKey: ["own-orders", accountId, "detail", id],
    queryFn: ({ signal }) =>
      auth.withAccount(accountId, (t) => loadOrder(id, accountId, t, signal)),
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  async function cancel(order: Order) {
    if (lock.current || auth.busy) return;
    lock.current = true;
    setBusy(true);
    setFailure("");
    setConfirmCancellation(false);
    try {
      const result = await auth.withAccount(accountId, (t) =>
        cancelOrder(order, accountId, t),
      );
      if (mounted.current)
        client.setQueryData(["own-orders", accountId, "detail", id], result);
    } catch (error) {
      if (mounted.current)
        setFailure(
          `${orderFailure(error)} Обновляем статус перед следующим действием.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) {
        setBusy(false);
        void client.invalidateQueries({ queryKey: ["own-orders", accountId] });
      }
    }
  }
  const order = detail.data;
  return (
    <article className="order-ticket" aria-label="Талон заказа">
      <div className="ticket-heading">
        <p className="eyebrow">Талон на выдачу</p>
        <button
          className="ticket-refresh"
          aria-label="Обновить статус заказа"
          disabled={detail.isFetching || busy}
          onClick={() => void detail.refetch()}
        >
          <RefreshCw size={17} />
        </button>
      </div>
      {detail.isPending ? (
        <p role="status">Проверяем актуальный статус…</p>
      ) : detail.isError ? (
        <p role="alert">{orderFailure(detail.error)}</p>
      ) : null}
      {order && (
        <>
          <h3>{order.order_number}</h3>
          <p className={`order-status status-${order.status.toLowerCase()}`}>
            {STATUS_LABELS[order.status]}
          </p>
          <p className="ticket-time">
            {formatSlot(order.slot_start_time, order.slot_end_time)}
          </p>
          <ul>
            {order.items.map((item) => (
              <li key={item.id}>
                <span>
                  {item.name_at_moment} × {item.quantity}
                </span>
                <strong>{money(item.price_at_moment * item.quantity)}</strong>
              </li>
            ))}
          </ul>
          <div className="ticket-total">
            <span>Сумма заказа</span>
            <strong>{money(order.total_amount)}</strong>
          </div>
          <p className="payment-evidence" role="status">{paymentLabel(order.payment_status)}</p>
          {order.payment_status === "DEMO_REFUNDED" && <p className="order-smallprint">Возврат подтверждён сервером. Повторная проверка не создаёт новый возврат.</p>}
          <p className="order-smallprint">
            Покажите номер сотруднику. Статус — по последнему обновлению.
          </p>
          {canCancel(order, accountId) && (
            <button
              className="cancel-order"
              disabled={
                busy || auth.busy || detail.isFetching || detail.isError
              }
              onClick={() => setConfirmCancellation(true)}
            >
              {busy ? "Проверяем отмену…" : "Отменить заказ"}
            </button>
          )}
          {confirmCancellation && canCancel(order, accountId) && (
            <div
              className="cancellation-confirmation"
              role="alertdialog"
              aria-label="Подтверждение отмены заказа"
            >
              <p>Отменить заказ {order.order_number}?</p>
              <button
                className="text-button"
                autoFocus
                onClick={() => setConfirmCancellation(false)}
              >
                Сохранить заказ
              </button>
              <button
                className="cancel-order"
                disabled={
                  busy || auth.busy || detail.isFetching || detail.isError
                }
                onClick={() => void cancel(order)}
              >
                Да, отменить заказ
              </button>
            </div>
          )}
          {!canCancel(order, accountId) && order.status !== "CANCELLED" && (
            <p className="order-smallprint">
              Отмена доступна только до приготовления и начала выбранного
              времени.
            </p>
          )}
        </>
      )}
      {failure && (
        <p role="alert" className="order-feedback">
          <AlertCircle size={16} />
          {failure}
        </p>
      )}
    </article>
  );
}
