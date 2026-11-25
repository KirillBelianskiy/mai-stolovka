"use client";

import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { BackContext, BottomAction, CAMPUS, ScreenHeader, Sheet, positionCount } from "@/components/customer-ui";
import { DishPhoto } from "@/components/dish-photo";
import { MenuFeed } from "@/components/menu-feed";
import { DishDetails } from "@/components/dish-details";
import { CheckoutPanel, OrderPanel, OrdersPanel } from "@/components/order-workspace";
import { ProfilePanel } from "@/components/profile-panel";
import { useTelegramChrome } from "@/components/telegram-chrome";
import { JOURNAL_KEY, type CheckoutIntent } from "@/lib/checkout";
import {
  CART_KEY, MAX_INTEGER, cartTotal, decodeCart, loadItem, money, saveCart,
  setQuantity, type CartLine, type MenuItem,
} from "@/lib/menu";

type Route =
  | { screen: "menu" | "cart" | "checkout" | "history" | "profile" }
  | { screen: "dish"; item: MenuItem }
  | { screen: "order"; id: string; accepted: boolean };

export function MenuApp() {
  const auth = useAuth();
  if (auth.status === "authenticated" && auth.credentials) {
    return <Customer key={auth.credentials.user.id} accountId={auth.credentials.user.id} />;
  }
  return <Launch />;
}

function Launch() {
  const auth = useAuth();
  useTelegramChrome(false, () => {});
  const loading = auth.status === "loading";
  return (
    <main className="customer-app launch-scene">
      <div className="photo-banner lunch-art launch-banner">
        <h1>{CAMPUS}</h1>
        <p>Столовая МАИ</p>
      </div>
      <div className="screen-content launch-status">
        {loading ? (
          <div role="status">
            <h2>Открываем меню</h2>
            <p>Входим через Telegram…</p>
          </div>
        ) : (
          <>
            <h2>{auth.error ? "Не удалось открыть меню" : "Вход в МАИ.Еда"}</h2>
            <p role={auth.error ? "alert" : undefined}>
              {auth.error ?? "Откройте приложение внутри Telegram."}
            </p>
            {(auth.error || auth.canUseTelegram) && (
              <button
                className="primary-button"
                disabled={auth.busy}
                onClick={() => void (auth.error ? auth.retry() : auth.signIn())}
              >
                {auth.error ? "Повторить" : "Войти через Telegram"}
              </button>
            )}
          </>
        )}
      </div>
    </main>
  );
}

function Customer({ accountId }: { accountId: string }) {
  const [stack, setStack] = useState<Route[]>([{ screen: "menu" }]);
  const route = stack[stack.length - 1];
  const [checkoutOpened, setCheckoutOpened] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const dismissals = useRef<Array<() => void>>([]);
  const backContext = useMemo(() => ({
    register(dismiss: () => void) {
      dismissals.current.push(dismiss);
      return () => { dismissals.current = dismissals.current.filter((entry) => entry !== dismiss); };
    },
  }), []);
  const back = useCallback(() => {
    const dismiss = dismissals.current.at(-1);
    if (dismiss) dismiss();
    else setStack((current) => current.length > 1 ? current.slice(0, -1) : current);
  }, []);
  useTelegramChrome(stack.length > 1, back);
  useEffect(() => {
    // Existing notification and browser links use plain fragments. Telegram launch data stays intact.
    function followLink() {
      switch (window.location.hash) {
        case "#orders":
          setStack([{ screen: "menu" }, { screen: "history" }]);
          break;
        case "#cart":
          setStack([{ screen: "menu" }, { screen: "cart" }]);
          break;
        case "#profile":
          setStack([{ screen: "menu" }, { screen: "profile" }]);
          break;
        case "#menu":
        case "#venue":
          setStack([{ screen: "menu" }]);
          break;
      }
    }
    followLink();
    window.addEventListener("hashchange", followLink);
    return () => window.removeEventListener("hashchange", followLink);
  }, []);
  const home = () => setStack([{ screen: "menu" }]);
  function open(next: Route) {
    if (next.screen === "checkout") setCheckoutOpened(true);
    setStack((current) => [...current, next]);
  }
  useLayoutEffect(() => {
    const focused = document.activeElement;
    if (route.screen !== "menu" && (!panel.current?.contains(focused) || focused?.closest("[hidden]"))) {
      panel.current?.focus({ preventScroll: true });
    }
  }, [route.screen]);

  const client = useQueryClient();
  const [cart, setCart] = useState<CartLine[]>([]);
  const basket = useRef(cart);
  const [hydrated, setHydrated] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  const [notice, setNotice] = useState("");
  const [cartFeedback, setCartFeedback] = useState("");
  const [journalPresent, setJournalPresent] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const emptyBasketHeading = useRef<HTMLHeadingElement>(null);
  const focusEmptyBasket = useRef(false);

  useLayoutEffect(() => {
    if (route.screen !== "cart" || cart.length !== 0 || !focusEmptyBasket.current) return;
    emptyBasketHeading.current?.focus({ preventScroll: true });
    focusEmptyBasket.current = false;
  }, [route.screen, cart.length]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(CART_KEY);
      if (saved !== null) {
        try {
          basket.current = decodeCart(saved);
          setCart(basket.current);
        } catch {
          setStorageWarning("Не удалось восстановить корзину. Соберите её заново.");
        }
      }
    } catch {
      setStorageWarning("Корзина сохранится только до закрытия страницы.");
    }
    try {
      setJournalPresent(sessionStorage.getItem(JOURNAL_KEY) !== null);
    } catch {
      // The checkout retains its own storage guard.
    }
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(CART_KEY, saveCart(cart));
    } catch {
      setStorageWarning("Корзина сохранится только до закрытия страницы.");
    }
  }, [cart, hydrated]);

  const cartQueries = useQueries({
    queries: cart.map((line) => ({
      queryKey: ["menu-item", line.id],
      queryFn: ({ signal }: { signal: AbortSignal }) => loadItem(line.id, signal),
      staleTime: 30000,
      retry: 1,
    })),
  });
  const currentCartItems = cartQueries.flatMap((query) =>
    query.data && !query.isError ? [query.data] : [],
  );
  const total = cartTotal(cart, currentCartItems);
  const quantity = cart.reduce((sum, line) => sum + line.quantity, 0);

  function updateCart(next: CartLine[]) {
    if (basket.current.length > 0 && next.length === 0 && route.screen === "cart") focusEmptyBasket.current = true;
    basket.current = next;
    setCart(next);
    setCartFeedback("");
  }
  function change(id: string, delta: number) {
    try {
      const existing = basket.current.find((line) => line.id === id)?.quantity ?? 0;
      updateCart(setQuantity(basket.current, id, Math.max(0, existing + delta)));
    } catch {
      setCartFeedback("Не удалось изменить количество. Уберите лишние позиции.");
    }
  }
  function add(item: MenuItem, count = 1) {
    if (!hydrated || !item.is_available) return false;
    try {
      const amount = (basket.current.find((line) => line.id === item.id)?.quantity ?? 0) + count;
      const next = setQuantity(basket.current, item.id, amount);
      // A catalog card can seed the basket, but must not overwrite a newer detail response.
      client.setQueryData<MenuItem>(["menu-item", item.id], (cached) => cached ?? item);
      updateCart(next);
      setNotice(item.name + " · В корзине " + amount);
      return true;
    } catch {
      setCartFeedback("Не удалось добавить блюдо. Уменьшите количество или уберите позицию.");
      return false;
    }
  }
  function complete(intent: CheckoutIntent) {
    const lines = basket.current
      .map((line) => ({ menu_item_id: line.id, quantity: line.quantity }))
      .sort((a, b) => a.menu_item_id.localeCompare(b.menu_item_id));
    if (JSON.stringify(lines) === JSON.stringify(intent.body.items)) updateCart([]);
    setJournalPresent(false);
  }

  const showCart = () => open({ screen: "cart" });
  return (
    <BackContext.Provider value={backContext}>
      <main className="customer-app">
        <MenuFeed
          active={route.screen === "menu"}
          openDish={(item) => open({ screen: "dish", item })}
          openProfile={() => open({ screen: "profile" })}
          cart={cart}
          canAdd={hydrated}
          add={add}
          feedback={cartFeedback || storageWarning}
          dock={quantity > 0 || journalPresent ? (
            <BottomAction>
              <button className="primary-button basket-link" onClick={quantity > 0 ? showCart : () => open({ screen: "checkout" })}>
                <span>{quantity > 0 ? "Корзина · " + quantity : "Продолжить оформление"}</span>
                {quantity > 0 && total !== null && <strong>{money(total)}</strong>}
              </button>
            </BottomAction>
          ) : null}
        />
        <div className="customer-panels" hidden={route.screen === "menu"} ref={panel} tabIndex={-1}>
          {route.screen === "dish" && (
            <DishDetails item={route.item} onBack={back} onAdd={add} onCart={showCart}
              inCart={cart.find((line) => line.id === route.item.id)?.quantity ?? 0}
              feedback={cartFeedback}
            />
          )}
          {route.screen === "cart" && (
            <section className="scene basket-scene" aria-labelledby="basket-heading">
              <div className={cart.length ? "photo-banner lunch-art basket-banner" : ""}>
                <ScreenHeader onBack={back} />
                {cart.length > 0 && <h1 id="basket-heading">Ваш обед</h1>}
                {cart.length > 0 && <p>{positionCount(cart.length)}</p>}
              </div>
              {cart.length === 0 ? (
                <>
                  <div className="screen-content empty-screen">
                    <div className="state-art plane-art" />
                    <h1 id="basket-heading" ref={emptyBasketHeading} tabIndex={-1}>Корзина пуста</h1>
                    <p>Добавьте блюдо из меню.</p>
                  </div>
                  <BottomAction><button className="primary-button" onClick={home}>В меню</button></BottomAction>
                </>
              ) : (
                <>
                  <div className="screen-content basket-content">
                    <ul className="basket-lines">
                      {cart.map((line, index) => {
                        const query = cartQueries[index];
                        const item = query.data;
                        const name = item?.name ?? (query.isPending ? "Загружаем блюдо…" : "Блюдо недоступно");
                        const unavailable = query.isError || !item?.is_available;
                        return (
                          <li key={line.id}>
                            <DishPhoto item={item ?? { image_url: null }} />
                            <div className="basket-line-name">
                              <h2>{name}</h2>
                              {item && <p>{money(item.price)}{line.quantity > 1 ? " за порцию" : ""}</p>}
                              {item && line.quantity > 1 && !unavailable && Number.isSafeInteger(item.price * line.quantity)
                                && <strong>{money(item.price * line.quantity)}</strong>}
                              {(query.isError || item?.is_available === false) && (
                                <p className="error-text">
                                  Недоступно <button className="text-button" onClick={() => void query.refetch()}>Проверить</button>
                                </p>
                              )}
                            </div>
                            <div className="quantity-control" role="group" aria-label={"Количество: " + name}>
                              <button aria-label={"Уменьшить количество: " + name} onClick={() => change(line.id, -1)}>
                                <Minus size={16} aria-hidden="true" />
                              </button>
                              <span aria-live="polite">{line.quantity}</span>
                              <button aria-label={"Увеличить количество: " + name}
                                onClick={() => change(line.id, 1)} disabled={unavailable || line.quantity >= MAX_INTEGER}>
                                <Plus size={16} aria-hidden="true" />
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                    <div className="basket-total"><span>Итого</span><strong>{total === null ? "—" : money(total)}</strong></div>
                    {total === null && <p role="status">Проверяем цены и доступность блюд. Уберите недоступные позиции, чтобы продолжить.</p>}
                    <button className="text-button basket-clear" onClick={() => setConfirmClear(true)}>
                      Очистить корзину
                    </button>
                    {(cartFeedback || storageWarning) && <p role="status">{cartFeedback || storageWarning}</p>}
                  </div>
                  <BottomAction>
                    <button className="primary-button" disabled={total === null && !journalPresent}
                      onClick={() => open({ screen: "checkout" })}>
                      Выбрать время
                    </button>
                  </BottomAction>
                  {confirmClear && (
                    <Sheet title="Очистить корзину?" alert onDismiss={() => setConfirmClear(false)}>
                      <button className="primary-button" autoFocus onClick={() => setConfirmClear(false)}>Оставить блюда</button>
                      <button className="text-button danger-button" onClick={() => {
                        setConfirmClear(false);
                        updateCart([]);
                        setNotice("Корзина очищена");
                      }}>Очистить корзину</button>
                    </Sheet>
                  )}
                </>
              )}
            </section>
          )}
          {checkoutOpened && (
            <div hidden={route.screen !== "checkout"}>
              <CheckoutPanel
                active={route.screen === "checkout"}
                cart={cart}
                items={currentCartItems}
                total={total}
                onBack={back}
                onHistory={() => open({ screen: "history" })}
                onComplete={complete}
                onOrder={(id, accepted) => setStack([{ screen: "menu" }, { screen: "order", id, accepted }])}
                onMenu={home}
                onJournal={setJournalPresent}
              />
            </div>
          )}
          {route.screen === "profile" &&
            <ProfilePanel onBack={back} onHistory={() => open({ screen: "history" })} />}
          <div hidden={route.screen !== "history"}>
            <OrdersPanel
              active={route.screen === "history"}
              onBack={back}
              onMenu={home}
              onOrder={(id) => open({ screen: "order", id, accepted: false })}
            />
          </div>
          {route.screen === "order" &&
            <OrderPanel key={route.id} accountId={accountId} id={route.id} accepted={route.accepted}
              onBack={back} onMenu={home} />}
        </div>
        <span className="sr-only" role="status">{notice}</span>
      </main>
    </BackContext.Provider>
  );
}
