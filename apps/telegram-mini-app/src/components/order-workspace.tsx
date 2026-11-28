"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Check, ChevronRight } from "lucide-react";
import {
  BottomAction, CAMPUS, ScreenHeader, Sheet, moscowDate, moscowDay,
  pickupTime, positionCount,
} from "@/components/customer-ui";
import { DishPhoto } from "@/components/dish-photo";
import { useAuth } from "@/components/auth-provider";
import {
  createIntent,
  persistIntent,
  readIntent,
  removeIntent,
  type CheckoutIntent,
} from "@/lib/checkout";
import { loadItem, money, type CartLine, type MenuItem } from "@/lib/menu";
import {
  canCancel,
  cancelOrder,
  createOrder,
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
  active: boolean;
  items: MenuItem[];
  onBack: () => void;
  onHistory: () => void;
  onMenu: () => void;
  onOrder: (id: string, accepted: boolean) => void;
  onJournal: (present: boolean) => void;
};
const knownRejections = new Set([
  "PRICE_CHANGED",
  "SLOT_FULL",
  "SLOT_CLOSED",
  "SLOT_NOT_FOUND",
  "TOTAL_TOO_LARGE",
  "INSUFFICIENT_FUNDS",
  "INSUFFICIENT_STOCK",
  "MENU_ITEM_NOT_FOUND",
  "MENU_ITEM_UNAVAILABLE",
  "DISH_UNAVAILABLE",
  "ITEM_UNAVAILABLE",
]);

export function CheckoutPanel(props: CheckoutProps) {
  const auth = useAuth();
  if (auth.status !== "authenticated" || !auth.credentials) return null;
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
  onComplete, active, items, onBack, onHistory, onMenu, onOrder, onJournal,
}: CheckoutProps & { accountId: string }) {
  const auth = useAuth(),
    client = useQueryClient();
  const [intent, setIntent] = useState<CheckoutIntent | null>(null),
    [ready, setReady] = useState(false),
    [storageError, setStorageError] = useState(false);
  const [slotId, setSlotId] = useState(""),
    [submission, setSubmission] = useState<"new" | "recovery" | null>(null),
    [failure, setFailure] = useState("");
  const [price, setPrice] = useState<{
      total: number;
      cart: string;
      slot: string;
      previous: number;
    } | null>(null),
    [ticket, setTicket] = useState<string | null>(null),
    [slotRejection, setSlotRejection] = useState<{ title: string; time: string; message: string } | null>(null);
  const [focusSlots, setFocusSlots] = useState(false);
  const slotHeading = useRef<HTMLHeadingElement>(null);
  const recoveryHeading = useRef<HTMLHeadingElement>(null);
  const [clearWarning, setClearWarning] = useState(false);
  const busy = submission !== null;
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
    queryFn: ({ signal }) =>
      auth.withAccount(accountId, (t) => loadWallet(accountId, t, signal)),
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
    setSubmission(recovering ? "recovery" : "new");
    setFailure("");
    setSlotRejection(null);
    let attempted = false;
    try {
      if (saved.account_id !== accountId)
        throw new Error("Wrong account intent");
      persistIntent(sessionStorage, saved);
      setIntent(saved);
      onJournal(true);
      setStorageError(false);
      attempted = true;
      const result = await auth.withAccount(accountId, (t) =>
        createOrder(saved, t),
      );
      if (!mounted.current) return;

      void client.invalidateQueries({ queryKey: ["menu-items"] });
      void client.invalidateQueries({ queryKey: ["menu-item"] });
      void client.invalidateQueries({ queryKey: ["own-orders", accountId] });
      try {
        removeIntent(sessionStorage, saved.key);
      } catch {
        setTicket(result.id);
        setStorageError(true);
        setFailure(
          "Заказ подтверждён, но ключ восстановления не удалось удалить. Новый заказ заблокирован; сначала проверьте талон и историю.",
        );
        return;
      }
      setIntent(null);
      setPrice(null);
      setSlotId("");
      onComplete(saved);
      onOrder(result.id, !recovering);
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
      if (rejection && error.code === "INSUFFICIENT_STOCK") {
        void client.invalidateQueries({ queryKey: ["menu-item"] });
        void client.invalidateQueries({ queryKey: ["menu-items"] });
      }
      if (rejection) {
        try {
          removeIntent(sessionStorage, saved.key);
          setIntent(null);
          onJournal(false);
          if (error.code === "PRICE_CHANGED" && error.totalAmount !== null)
            setPrice({
              total: error.totalAmount,
              previous: saved.body.expected_total_amount,
              cart: JSON.stringify(saved.body.items),
              slot: saved.body.slot_id,
            });
          if (error.code === "SLOT_FULL" || error.code === "SLOT_CLOSED" || error.code === "SLOT_NOT_FOUND") {
            const rejected = choices.find((slot) => slot.id === saved.body.slot_id);
            setSlotRejection({
              title: error.code === "SLOT_FULL" ? "Время уже занято" : "Время уже недоступно",
              time: rejected ? pickupTime(rejected.start_time, rejected.end_time) : "",
              message: orderFailure(error),
            });
            setSlotId("");
            setPrice(null);
          }
        } catch {
          setStorageError(true);
        }
      }
      setFailure(orderFailure(error));
      void slots.refetch();
    } finally {
      lock.current = false;
      if (mounted.current) {
        setSubmission(null);
        void client.invalidateQueries({
          queryKey: ["own-orders", accountId, "wallet"],
        });
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
      onJournal(false);
      if (ticket) {
        onOrder(ticket, true);
        setTicket(null);
      }
    } catch {
      setStorageError(true);
      setFailure("Не удалось очистить данные. Новый заказ заблокирован.");
    }
  }

  useLayoutEffect(() => {
    if (active && (slotRejection || priceApplicable)) recoveryHeading.current?.focus();
  }, [active, slotRejection, priceApplicable]);
  useLayoutEffect(() => {
    if (active && focusSlots && !slots.isFetching) {
      slotHeading.current?.focus();
      setFocusSlots(false);
    }
  }, [active, focusSlots, slots.isFetching]);

  const showIntent = intent && submission !== "new";
  const recoveringIntent = showIntent && intent.account_id === accountId;
  const groups = new Map<string, typeof choices>();
  for (const slot of choices) {
    const day = moscowDay(slot.start_time);
    groups.set(day, [...(groups.get(day) ?? []), slot]);
  }
  const firstDay = choices[0]?.start_time;
  const readiness = wallet.data?.checkout_payment_enabled && total !== null
    ? Math.max(0, (priceApplicable ? price.total : total) - wallet.data.balance)
    : 0;
  const recovery = slotRejection || priceApplicable;
  const heading = recovery || showIntent || storageError ? "Оформление" : "Когда заберёте?";
  const summaryArt = (
    <div className="checkout-thumbs">
      {items.slice(0, 3).map((item) => <DishPhoto key={item.id} item={item} />)}
    </div>
  );

  return (
    <section className="scene checkout-scene" aria-labelledby="checkout-heading">
      <div className={"photo-banner checkout-banner " + (recovery ? "lunch-art" : "plane-art")}>
        <ScreenHeader onBack={onBack} />
        <h1 id="checkout-heading">{heading}</h1>
        {!recovery && !showIntent && !storageError && (
          <p>{firstDay && groups.size === 1 ? moscowDate(firstDay) + " · " : ""}время московское</p>
        )}
      </div>
      <div className="screen-content checkout-content">
        {!ready ? (
          <p role="status">Проверяем незавершённые запросы…</p>
        ) : storageError ? (
          <div className="checkout-warning" role="alert">
            <p>Хранилище вкладки недоступно или сохранённый запрос повреждён. Оформление заблокировано.</p>
            <button className="text-button" disabled={busy} onClick={() => setClearWarning(true)}>
              Очистить данные с предупреждением
            </button>
          </div>
        ) : showIntent ? (
          <div className="checkout-warning" role="status">
            <h2>{recoveringIntent ? "Есть незавершённый запрос" : "Есть запрос другого аккаунта"}</h2>
            {recoveringIntent ? (
              <p>Проверим исходный заказ на {money(intent.body.expected_total_amount)}. Корзина сохранена.</p>
            ) : (
              <p>Вернитесь в исходный аккаунт, чтобы проверить запрос.</p>
            )}
            <button className="text-button" disabled={busy} onClick={onHistory}>Сначала проверить историю</button>
            <button className="text-button" disabled={busy} onClick={() => setClearWarning(true)}>
              Очистить данные с предупреждением
            </button>
          </div>
        ) : slotRejection ? (
          <div className="checkout-recovery">
            <h2 ref={recoveryHeading} tabIndex={-1}>{slotRejection.title}</h2>
            <p>Корзина сохранена.</p>
            {summaryArt}
            <div className="recovery-totals">
              {slotRejection.time && <p className="rejected-time">{slotRejection.time}</p>}
              <p>{slotRejection.message}</p>
            </div>
          </div>
        ) : priceApplicable ? (
          <div className="checkout-recovery">
            <h2 ref={recoveryHeading} tabIndex={-1}>Цена изменилась</h2>
            <p>Проверьте новый итог.</p>
            {summaryArt}
            <dl className="recovery-totals">
              <div><dt>Было</dt><dd>{money(price.previous)}</dd></div>
              <div><dt>Стало</dt><dd>{money(price.total)}</dd></div>
            </dl>
            {!valid && (
              <button className="text-button" onClick={() => {
                setPrice(null);
                setSlotId("");
                setFocusSlots(true);
                void slots.refetch();
              }}>Выбрать другое время</button>
            )}
          </div>
        ) : (
          <>
            <h2 className="sr-only" ref={slotHeading} tabIndex={-1}>Интервалы выдачи</h2>
            {slots.isPending && <p role="status">Загружаем время выдачи…</p>}
            {slots.isError && (
              <p role="alert">
                Не удалось обновить время.{" "}
                <button className="text-button" onClick={() => void slots.refetch()}>Повторить загрузку</button>
              </p>
            )}
            {!slots.isPending && !slots.isError && choices.length === 0 && (
              <p>Пока нет доступного времени. Проверьте позже.</p>
            )}
            <div role="group" aria-label="Интервалы выдачи">
              {[...groups].map(([day, slotsForDay]) => (
                <div className="slot-group" key={day}>
                  {groups.size > 1 && <h3>{moscowDate(slotsForDay[0].start_time)}</h3>}
                  {slotsForDay.map((slot) => {
                    const expired = Date.parse(slot.start_time) <= Date.now();
                    const full = slot.remaining_capacity <= 0;
                    const picked = slot.id === slotId && !expired && !full;
                    const interval = pickupTime(slot.start_time, slot.end_time);
                    const availability = expired ? "Приём заказов завершён" : full ? "Мест нет" : picked ? "Выбрано" : "Есть места";
                    return (
                      <button key={slot.id} type="button" className="pickup-slot" data-full={full && !expired} aria-pressed={picked} aria-label={interval + " · " + availability}
                        disabled={busy || auth.busy || expired || full}
                        onClick={() => {
                          setSlotId(slot.id);
                          setPrice(null);
                          setFailure("");
                        }}>
                        <span>
                          <strong>{interval}</strong>
                          <small>{availability}</small>
                        </span>
                        <span className="slot-indicator" aria-hidden="true">{picked && <Check size={15} />}</span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="slot-actions">
              <button className="text-button" disabled={slots.isFetching || busy}
                onClick={() => void slots.refetch()}>Обновить время</button>
              {slots.hasNextPage && (
                <button className="text-button" disabled={slots.isFetching || busy}
                  onClick={() => void slots.fetchNextPage()}>Ещё интервалы</button>
              )}
            </div>
            {cart.length > 0 && (
              <section className="checkout-summary">
                <h2>Ваш обед</h2>
                <div>{summaryArt}<strong>{positionCount(cart.length)} · {total === null ? "—" : money(total)}</strong></div>
              </section>
            )}
          </>
        )}
        <section className="demo-wallet" aria-label="Демонстрационный баланс">
          {wallet.isPending && <p role="status">Проверяем демобаланс…</p>}
          {wallet.isError && <p role="alert">Не удалось обновить демобаланс. Обновите баланс перед новым заказом.</p>}
          {wallet.data && (
            <>
              <p>Демобаланс <strong>{money(wallet.data.balance)}</strong></p>
              {!wallet.data.checkout_payment_enabled && !wallet.isError && <p>Оплата не требуется</p>}
              {readiness > 0 && <p className="error-text">Не хватает {money(readiness)}. Обновите баланс после пополнения.</p>}
            </>
          )}
          <button className="text-button" disabled={wallet.isFetching || busy || auth.busy}
            onClick={() => void wallet.refetch()}>Обновить демобаланс</button>
        </section>
        {failure && !recovery && (
          <p role="alert" className="order-feedback">
            {failure}
            {recoveringIntent && " Проверьте исходный запрос перед новым заказом."}
          </p>
        )}
        {ticket && <OrderTicket accountId={accountId} id={ticket} accepted onMenu={onMenu} />}
      </div>
      {!ticket && (
        <BottomAction>
          {recoveringIntent && !storageError ? (
            <button className="primary-button" disabled={busy || auth.busy} onClick={() => void send(intent, true)}>
              {busy ? "Проверяем результат…" : "Восстановить исходный заказ"}
            </button>
          ) : slotRejection ? (
            <button className="primary-button" onClick={() => {
              setSlotRejection(null);
              setFailure("");
              setFocusSlots(true);
            }}>Выбрать другое время</button>
          ) : ready && !storageError && !showIntent ? (
            <button className="primary-button" disabled={!valid || !paymentReady || busy}
              onClick={() => {
                const amount = priceApplicable ? price.total : total;
                if (amount !== null) start(amount);
              }}>
              {submission === "new" ? "Подтверждаем заказ…" : priceApplicable ? "Подтвердить новую сумму · " + money(price.total) :
                total !== null ? "Подтвердить · " + money(total) : "Подтвердить заказ"}
            </button>
          ) : null}
        </BottomAction>
      )}
      {active && clearWarning && (
        <Sheet title="Предупреждение об очистке запроса" alert onDismiss={() => setClearWarning(false)}>
          <p>Заказ мог быть создан. Сначала проверьте историю. Повторное оформление после удаления ключа может создать ещё один заказ.</p>
          <button className="primary-button" disabled={busy} autoFocus onClick={() => setClearWarning(false)}>Вернуться к запросу</button>
          <button className="text-button danger-button" disabled={busy} onClick={clear}>Удалить ключ восстановления</button>
        </Sheet>
      )}
    </section>
  );
}

type HistoryProps = {
  active: boolean;
  onBack: () => void;
  onMenu: () => void;
  onOrder: (id: string) => void;
};

export function OrdersPanel(props: HistoryProps) {
  const auth = useAuth();
  const client = useQueryClient();
  const id = auth.status === "authenticated" && auth.credentials?.user.role === "CLIENT"
    ? auth.credentials.user.id : null;
  useEffect(
    () => () => {
      if (id) {
        void client.cancelQueries({ queryKey: ["own-orders", id] });
        client.removeQueries({ queryKey: ["own-orders", id] });
      }
    },
    [client, id],
  );
  return id ? <OrderHistory key={id} accountId={id} {...props} /> : null;
}

function OrderHistory({ accountId, active, onBack, onMenu, onOrder }: HistoryProps & { accountId: string }) {
  const auth = useAuth();
  const [offset, setOffset] = useState(0);
  const lastOrder = useRef<string | null>(null);
  const viewport = useRef<HTMLElement>(null);
  const scroll = useRef(0);
  const history = useQuery({
    queryKey: ["own-orders", accountId, "history", offset],
    queryFn: ({ signal }) => auth.withAccount(accountId, (t) => loadOrders(accountId, t, offset, signal)),
    enabled: active,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  useLayoutEffect(() => {
    const scene = viewport.current;
    if (!active || !lastOrder.current || !scene) return;
    const frame = requestAnimationFrame(() => {
      scene.scrollTop = scroll.current;
      const row = Array.from(scene.querySelectorAll<HTMLButtonElement>("[data-history-order]"))
        .find((button) => button.dataset.historyOrder === lastOrder.current);
      (row ?? scene.querySelector<HTMLElement>("#orders-heading"))?.focus({ preventScroll: true });
      lastOrder.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [active]);
  const today = moscowDay(Date.now());
  const orders = history.data?.items ?? [];
  const highlighted = orders.filter((order) => (moscowDay(order.slot_start_time) === today || moscowDay(order.created_at) === today) &&
    order.status !== "COMPLETED" && order.status !== "CANCELLED");
  const remaining = orders.filter((order) => !highlighted.includes(order));
  function open(id: string) {
    lastOrder.current = id;
    scroll.current = viewport.current?.scrollTop ?? 0;
    onOrder(id);
  }
  return (
    <section ref={viewport} className="scene history-scene" aria-labelledby="orders-heading">
      <ScreenHeader onBack={onBack} />
      <div className="screen-content">
        <h1 id="orders-heading" tabIndex={-1}>Мои заказы</h1>
        {history.isPending && <p role="status">Загружаем заказы…</p>}
        {history.isError && <p role="alert">{orderFailure(history.error)}{orders.length > 0 && " Показаны последние загруженные данные."}</p>}
        {history.data && !orders.length && (
          <div className="empty-screen">
            <div className="state-art lunch-art" />
            <h2>Здесь появятся ваши заказы</h2>
            <p>Выберите первый обед в меню.</p>
          </div>
        )}
        {highlighted.length > 0 && (
          <section className="history-today">
            <h2>Сегодня</h2>
            {highlighted.map((order) => (
              <button className="history-feature" key={order.id} data-history-order={order.id} onClick={() => open(order.id)}>
                <span className="history-cover lunch-art">
                  <strong>{order.order_number}</strong>
                  <span className={"status-" + order.status.toLowerCase()}>{STATUS_LABELS[order.status]}</span>
                </span>
                <span className="history-row-main">
                  <strong>
                    {moscowDay(order.slot_start_time) !== today && moscowDate(order.slot_start_time) + " · "}
                    {pickupTime(order.slot_start_time, order.slot_end_time)}
                  </strong>
                  <strong>{money(order.total_amount)}</strong>
                  <ChevronRight size={17} aria-hidden="true" />
                </span>
                <span className="history-composition">{order.items.map((item) => item.name_at_moment).join(", ")}</span>
              </button>
            ))}
          </section>
        )}
        {remaining.length > 0 && (
          <section className="history-earlier">
            {highlighted.length > 0 && <h2>Другие заказы</h2>}
            {remaining.map((order) => (
              <button className="history-row" key={order.id} data-history-order={order.id} onClick={() => open(order.id)}>
                <span className="history-row-main">
                  <strong>{order.order_number}</strong>
                  <span>{money(order.total_amount)}</span>
                  <ChevronRight size={17} aria-hidden="true" />
                </span>
                <small>{moscowDate(order.slot_start_time)} · {pickupTime(order.slot_start_time, order.slot_end_time)} · {STATUS_LABELS[order.status]}</small>
              </button>
            ))}
          </section>
        )}
        <div className="history-actions">
          <button className="text-button" disabled={history.isFetching} onClick={() => void history.refetch()}>
            {history.isError ? "Повторить" : "Обновить историю"}
          </button>
          {history.data && (offset > 0 || history.data.total > 10) && (
            <nav className="order-pagination" aria-label="Страницы истории">
              <button className="text-button" disabled={offset === 0 || history.isFetching}
                onClick={() => setOffset(Math.max(0, offset - 10))}>Назад</button>
              <span>Страница {offset / 10 + 1}</span>
              <button className="text-button" disabled={offset + orders.length >= history.data.total || history.isFetching}
                onClick={() => setOffset(offset + 10)}>Дальше</button>
            </nav>
          )}
        </div>
      </div>
      {history.data && !orders.length && (
        <BottomAction><button className="primary-button" onClick={onMenu}>В меню</button></BottomAction>
      )}
    </section>
  );
}

type OrderViewProps = {
  accountId: string;
  id: string;
  accepted: boolean;
  onMenu: () => void;
};

export function OrderPanel({ onBack, ...order }: OrderViewProps & { onBack: () => void }) {
  return (
    <section className="scene order-scene">
      <OrderTicket {...order} onBack={onBack} />
    </section>
  );
}

const orderStages = [
  { status: "PENDING", label: "Принят" },
  { status: "PREPARING", label: STATUS_LABELS.PREPARING },
  { status: "READY", label: STATUS_LABELS.READY },
  { status: "COMPLETED", label: STATUS_LABELS.COMPLETED },
] as const;

function OrderTicket({ accountId, id, accepted, onMenu, onBack }: OrderViewProps & { onBack?: () => void }) {
  const auth = useAuth(), client = useQueryClient();
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  const [compositionOpen, setCompositionOpen] = useState(false);
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const lock = useRef(false), mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const detail = useQuery({
    queryKey: ["own-orders", accountId, "detail", id],
    queryFn: ({ signal }) => auth.withAccount(accountId, (t) => loadOrder(id, accountId, t, signal)),
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
  async function cancel(order: Order) {
    if (lock.current || auth.busy || !canCancel(order, accountId)) return;
    lock.current = true;
    setBusy(true);
    setFailure("");
    setConfirmCancellation(false);
    try {
      const result = await auth.withAccount(accountId, (t) => cancelOrder(order, accountId, t));
      if (mounted.current)
        client.setQueryData(["own-orders", accountId, "detail", id], result);
    } catch (error) {
      if (mounted.current)
        setFailure(orderFailure(error) + " Обновляем статус перед следующим действием.");
    } finally {
      lock.current = false;
      if (mounted.current) {
        setBusy(false);
        void client.invalidateQueries({ queryKey: ["own-orders", accountId] });
      }
    }
  }
  const order = detail.data;
  const pendingUntil = order?.status === "PENDING" ? Date.parse(order.slot_start_time) : 0;
  useEffect(() => {
    if (pendingUntil <= now) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.min(2_147_483_647, Math.max(0, pendingUntil - Date.now())));
    return () => window.clearTimeout(timer);
  }, [pendingUntil, now]);
  const canRequestCancel = Boolean(order && canCancel(order, accountId, Math.max(now, Date.now())));
  const cancellationDisabled = busy || auth.busy || detail.isFetching || detail.isError;
  const showAccepted = accepted && order?.status === "PENDING";
  const currentStage = orderStages.findIndex(({ status }) => status === order?.status);
  const title = order
    ? showAccepted ? "Заказ принят"
      : order.status === "COMPLETED" ? "Заказ выдан"
      : order.status === "CANCELLED" ? "Заказ отменён"
      : STATUS_LABELS[order.status]
    : accepted ? "Заказ принят" : "Заказ";
  const guidance = order?.status === "READY" ? "Покажите номер на выдаче"
    : showAccepted ? STATUS_LABELS.PENDING
    : order?.status === "PREPARING" ? "Обед готовят в столовой"
    : order?.status === "CANCELLED" ? "Выдача отменена"
    : order?.status === "COMPLETED" ? "Приятного аппетита!" : "";

  return (
    <article className="order-ticket" aria-label="Талон заказа">
      <div className="photo-banner plane-art order-banner" data-stage={order?.status}>
        {onBack && <ScreenHeader onBack={onBack} />}
        <div className="ticket-heading" aria-live="polite">
          <h1 className={order ? "status-" + order.status.toLowerCase() : undefined}>{title}</h1>
          {order && <p className="order-number">{order.order_number}</p>}
          {guidance && <p className="ticket-guidance">{guidance}</p>}
        </div>
        {currentStage >= 0 && (
          <ol className="order-progress" aria-label="Этапы заказа">
            {orderStages.map(({ status, label }, index) => (
              <li key={status} aria-current={index === currentStage ? "step" : undefined}
                data-complete={index <= currentStage}>
                <span className="sr-only">{label}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className="screen-content ticket-content">
        <div className="pickup-label">
          <span>Время выдачи</span>
          <button className="text-button" disabled={detail.isFetching || busy}
            onClick={() => void detail.refetch()}>Обновить</button>
        </div>
        {detail.isPending && <p role="status">Проверяем статус…</p>}
        {detail.isError && (
          <p role="alert">{orderFailure(detail.error)}{order && " Показан последний загруженный статус."}</p>
        )}
        {order && (
          <>
            <p className="pickup-time">
              <strong>{pickupTime(order.slot_start_time, order.slot_end_time)}</strong> <span>МСК</span>
            </p>
            <p>{moscowDate(order.slot_start_time)} · {CAMPUS}</p>
            <details className="ticket-composition" onToggle={(event) => setCompositionOpen(event.currentTarget.open)}>
              <summary>
                <span>Состав · {positionCount(order.items.length)}</span>
                <strong>{money(order.total_amount)}</strong>
              </summary>
              <ul>
                {order.items.map((item) => (
                  <li key={item.id}>
                    <ReceiptPhoto id={item.menu_item_id} visible={compositionOpen} />
                    <span>{item.name_at_moment}{item.quantity > 1 && <small>{item.quantity} × {money(item.price_at_moment)}</small>}</span>
                    <strong>{money(item.price_at_moment * item.quantity)}</strong>
                  </li>
                ))}
              </ul>
            </details>
            <p className="payment-evidence" role="status">{paymentLabel(order.payment_status)}</p>
            {canRequestCancel && (
              <button className="text-button danger-button cancel-order" disabled={cancellationDisabled}
                onClick={() => setConfirmCancellation(true)}>Отменить заказ</button>
            )}
            {confirmCancellation && canRequestCancel && (
              <Sheet title={"Отменить заказ " + order.order_number + "?"} alert onDismiss={() => setConfirmCancellation(false)}>
                <button className="primary-button" autoFocus onClick={() => setConfirmCancellation(false)}>Оставить заказ</button>
                <button className="text-button danger-button" disabled={cancellationDisabled}
                  onClick={() => void cancel(order)}>Отменить заказ</button>
              </Sheet>
            )}
          </>
        )}
        {failure && <p role="alert" className="order-feedback">{failure}</p>}
      </div>
      <BottomAction><button className="primary-button" onClick={onMenu}>Вернуться в меню</button></BottomAction>
    </article>
  );
}

function ReceiptPhoto({ id, visible }: { id: string; visible: boolean }) {
  const item = useQuery({
    queryKey: ["menu-item", id],
    queryFn: ({ signal }) => loadItem(id, signal),
    enabled: visible,
    staleTime: 30000,
    retry: false,
  });
  return <DishPhoto item={item.data ?? { image_url: null }} />;
}
