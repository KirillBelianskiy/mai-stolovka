"use client";

import {
  useInfiniteQuery,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowRight,
  Check,
  Minus,
  Plus,
  RotateCcw,
  Soup,
  Trash2,
  MapPin,
  Search,
  Ticket,
  UserRound,
  Utensils,
  X,
} from "lucide-react";
import { DishPhoto } from "@/components/dish-photo";
import { CheckoutPanel, OrdersPanel } from "@/components/order-workspace";
import { ProfilePanel } from "@/components/profile-panel";
import { useEffect, useRef, useState } from "react";
import {
  CART_KEY,
  MAX_INTEGER,
  addToCart,
  cartTotal,
  decodeCart,
  loadCategories,
  loadItem,
  loadItems,
  money,
  saveCart,
  setQuantity,
  type CartLine,
  type MenuItem,
} from "@/lib/menu";

type View = "venue" | "menu" | "cart" | "orders" | "profile";

function currentView(): View {
  const hash = window.location.hash.slice(1);
  return ["venue", "menu", "cart", "orders", "profile"].includes(hash)
    ? (hash as View)
    : "menu";
}

export function MenuApp() {
  const [view, setView] = useState<View>("menu");
  const [search, setSearch] = useState("");
  const [selectedDish, setSelectedDish] = useState<MenuItem | null>(null);
  useEffect(() => {
    const navigate = () => {
      setView(currentView());
      window.scrollTo(0, 0);
    };
    navigate();
    window.addEventListener("hashchange", navigate);
    return () => window.removeEventListener("hashchange", navigate);
  }, []);
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<string | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  const [notice, setNotice] = useState("");
  const categories = useQuery({
    queryKey: ["menu-categories"],
    queryFn: ({ signal }) => loadCategories(signal),
    retry: 1,
  });
  const menu = useInfiniteQuery({
    queryKey: ["menu-items", category],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => loadItems(category, pageParam, signal),
    getNextPageParam: (page) =>
      page.items.length > 0 && page.offset + page.items.length < page.total
        ? page.offset + page.items.length
        : undefined,
    retry: 1,
  });
  const cartQueries = useQueries({
    queries: cart.map((line) => ({
      queryKey: ["menu-item", line.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        loadItem(line.id, signal),
      staleTime: 30000,
      retry: 1,
    })),
  });
  const currentCartItems = cartQueries.flatMap((query) =>
    query.data && !query.isError ? [query.data] : [],
  );
  const total = cartTotal(cart, currentCartItems);
  const quantity = cart.reduce((sum, line) => sum + line.quantity, 0);
  const items = [
    ...new Map(
      menu.data?.pages
        .flatMap((page) => page.items)
        .map((item) => [item.id, item]) ?? [],
    ).values(),
  ];

  useEffect(() => {
    try {
      const saved = localStorage.getItem(CART_KEY);
      if (saved !== null) {
        try {
          setCart(decodeCart(saved));
        } catch {
          setStorageWarning(
            "Не удалось восстановить корзину. Соберите её заново.",
          );
        }
      }
    } catch {
      setStorageWarning("Корзина сохранится только до закрытия страницы.");
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

  function change(id: string, next: number) {
    try {
      setCart(setQuantity(cart, id, next));
      setNotice("");
    } catch {
      setNotice("Не удалось изменить количество. Уберите лишние позиции.");
    }
  }
  function add(item: MenuItem) {
    if (!hydrated || !item.is_available) return;
    try {
      const next = addToCart(cart, item.id);
      queryClient.setQueryData(["menu-item", item.id], item);
      setCart(next);
      setNotice(`${item.name} — добавлено в корзину`);
    } catch {
      setNotice(
        "В корзине может быть не больше 100 разных блюд. Уменьшите количество или уберите позицию.",
      );
    }
  }

  return (
    <div className="lunch-app">
      <a className="skip-link" href="#menu">
        Перейти к меню
      </a>
      <header className="app-header">
        <a href="#menu" className="wordmark" aria-label="МАИ Еда — к началу">
          <Wing />
          <span>МАИ еда</span>
        </a>
        <span className="header-edition">
          {view === "menu"
            ? "МЕНЮ"
            : view === "profile"
              ? "ПРОФИЛЬ"
              : "ВАШ ЗАКАЗ"}{" "}
          / МАИ
        </span>
      </header>
      <main>
        <section
          hidden={view !== "venue"}
          className="venue-screen"
          aria-labelledby="venue-title"
        >
          <p className="eyebrow">СТОЛОВАЯ МАИ</p>
          <h1 id="venue-title">Время на обед</h1>
          <p>Выберите блюда заранее — заберите в удобное время.</p>
          <a href="#menu" className="venue-card">
            <MapPin size={24} />
            <span>
              <strong>Столовая МАИ</strong>
              <small>Меню и доступное время выдачи</small>
            </span>
            <ArrowRight size={20} />
          </a>
        </section>
        <div className="menu-layout">
          <section
            id="menu"
            className="menu-section"
            hidden={view !== "menu"}
            aria-labelledby="menu-heading"
          >
            <div className="section-heading">
              <div>
                <h1 id="menu-heading">Меню на сегодня</h1>
              </div>
              <button
                className="refresh-button"
                onClick={() => {
                  void menu.refetch();
                  void categories.refetch();
                }}
                aria-label="Обновить меню"
                disabled={menu.isFetching}
              >
                <RotateCcw
                  size={17}
                  className={menu.isFetching ? "spinning" : ""}
                  aria-hidden="true"
                />
              </button>
            </div>
            <a href="#venue" className="venue-link">
              <MapPin size={20} /> Столовая МАИ <ArrowDown size={14} />
            </a>
            <label className="menu-search">
              <Search size={22} />
              <input
                type="search"
                aria-label="Найти блюдо"
                placeholder="Найти блюдо"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <div className="category-list" aria-label="Категории блюд">
              <button
                aria-pressed={category === null}
                onClick={() => setCategory(null)}
              >
                Все
              </button>
              {categories.data?.map((value) => (
                <button
                  key={value.id}
                  aria-pressed={category === value.id}
                  onClick={() => setCategory(value.id)}
                >
                  {value.name}
                </button>
              ))}
            </div>
            {categories.isError && (
              <p className="inline-note" role="status">
                Категории пока не загрузились. Все блюда доступны ниже.
              </p>
            )}
            {menu.isFetching && !menu.isPending && (
              <p className="updating-note" role="status">
                Обновляем меню…
              </p>
            )}
            {menu.isPending ? (
              <div
                role="status"
                aria-label="Меню загружается"
                className="dish-grid"
              >
                {[0, 1, 2, 3].map((value) => (
                  <div className="dish-skeleton" key={value}>
                    <span />
                    <span />
                    <span />
                  </div>
                ))}
              </div>
            ) : menu.isError && items.length === 0 ? (
              <div className="empty-state" role="alert">
                <Soup size={34} aria-hidden="true" />
                <h3>Меню пока недоступно</h3>
                <p>
                  Не удалось загрузить блюда. Проверьте подключение и попробуйте
                  ещё раз.
                </p>
                <button
                  className="primary-button"
                  onClick={() => void menu.refetch()}
                >
                  Попробовать ещё раз{" "}
                  <ArrowRight size={17} aria-hidden="true" />
                </button>
              </div>
            ) : items.length === 0 ? (
              <div className="empty-state">
                <Soup size={34} aria-hidden="true" />
                <h3>Здесь пока нет блюд</h3>
                <p>
                  {category
                    ? "Попробуйте другую категорию или обновите меню позже."
                    : "Блюда появятся, когда столовая обновит меню."}
                </p>
                {category && (
                  <button
                    className="text-button"
                    onClick={() => setCategory(null)}
                  >
                    Посмотреть всё меню
                  </button>
                )}
              </div>
            ) : (
              <div className="dish-grid">
                {items
                  .filter((item) =>
                    item.name
                      .toLocaleLowerCase("ru")
                      .includes(search.trim().toLocaleLowerCase("ru")),
                  )
                  .map((item) => (
                    <article className="dish-card" key={item.id}>
                      <button
                        className="dish-open"
                        aria-label={`Подробнее: ${item.name}`}
                        onClick={() => setSelectedDish(item)}
                      >
                        <DishPhoto item={item} />
                        <h3>{item.name}</h3>
                      </button>
                      <p className="dish-description">{money(item.price)}</p>
                      <div className="dish-bottom">
                        {cart.find((line) => line.id === item.id) ? (
                          <QuantityControl
                            name={item.name}
                            value={
                              cart.find((line) => line.id === item.id)!.quantity
                            }
                            onChange={(next) => change(item.id, next)}
                            disabled={
                              !item.is_available ||
                              cartQueries[
                                cart.findIndex((line) => line.id === item.id)
                              ]?.isError
                            }
                          />
                        ) : (
                          <button
                            className="add-button"
                            aria-label={`Добавить ${item.name} в корзину`}
                            onClick={() => add(item)}
                            disabled={!hydrated || !item.is_available}
                          >
                            {item.is_available ? (
                              <>
                                <span>Добавить · {money(item.price)}</span>
                              </>
                            ) : (
                              "Недоступно"
                            )}
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
              </div>
            )}
            {search &&
              !items.some((item) =>
                item.name
                  .toLocaleLowerCase("ru")
                  .includes(search.trim().toLocaleLowerCase("ru")),
              ) && (
                <p className="inline-note">
                  Среди загруженных блюд совпадений нет.{" "}
                  {menu.hasNextPage
                    ? "Загрузите ещё блюда или измените запрос."
                    : "Попробуйте другой запрос."}
                </p>
              )}
            {menu.isError && items.length > 0 && (
              <p className="inline-note" role="alert">
                Не удалось обновить список.{" "}
                <button
                  className="text-button"
                  onClick={() => void menu.refetch()}
                >
                  Повторить
                </button>
              </p>
            )}
            {menu.hasNextPage && (
              <button
                className="load-more"
                onClick={() => void menu.fetchNextPage()}
                disabled={menu.isFetchingNextPage}
              >
                {menu.isFetchingNextPage ? "Загружаем…" : "Ещё блюда"}
                <ArrowDown size={17} aria-hidden="true" />
              </button>
            )}
          </section>

          <aside
            id="cart"
            className="cart-panel"
            hidden={view !== "cart"}
            aria-labelledby="cart-heading"
          >
            <a className="back-link" href="#menu">
              ← Назад
            </a>
            <div className="cart-title">
              <h1 id="cart-heading">Ваш обед</h1>
            </div>
            <p className="cart-venue">Столовая МАИ</p>
            <a className="history-link" href="#orders">
              Мои заказы <ArrowRight size={16} />
            </a>
            {cart.length === 0 ? (
              <div className="cart-empty">
                <p>Начните с любимого.</p>
                <span>
                  Добавьте блюда из меню —<br />
                  они появятся здесь.
                </span>
                <a href="#menu">
                  Выбрать блюда <ArrowRight size={16} aria-hidden="true" />
                </a>
              </div>
            ) : (
              <>
                <ul className="cart-lines">
                  {cart.map((line, index) => {
                    const query = cartQueries[index];
                    const item = query.data;
                    const unavailable =
                      query.isError || (item && !item.is_available);
                    return (
                      <li
                        key={line.id}
                        className={
                          unavailable ? "cart-line unavailable" : "cart-line"
                        }
                      >
                        {item && <DishPhoto item={item} />}
                        <div className="cart-line-heading">
                          <h3>
                            {item?.name ??
                              (query.isPending
                                ? "Загружаем блюдо…"
                                : "Блюдо недоступно")}
                          </h3>
                          <button
                            className="remove-line"
                            aria-label={`Убрать ${item?.name ?? "блюдо"} из корзины`}
                            onClick={() => change(line.id, 0)}
                          >
                            <Trash2 size={15} aria-hidden="true" />
                          </button>
                        </div>
                        {unavailable ? (
                          <p className="cart-line-note">
                            Не удалось подтвердить доступность.{" "}
                            <button onClick={() => void query.refetch()}>
                              Проверить
                            </button>
                          </p>
                        ) : (
                          <p className="cart-unit-price">
                            {item
                              ? `${money(item.price)} за порцию`
                              : "Проверяем цену"}
                            {query.isFetching && item ? " · обновляем" : ""}
                          </p>
                        )}
                        <div className="cart-line-bottom">
                          <QuantityControl
                            name={item?.name ?? "блюдо"}
                            value={line.quantity}
                            onChange={(next) => change(line.id, next)}
                            disabled={!!unavailable}
                          />
                          <span>
                            {item &&
                            !unavailable &&
                            Number.isSafeInteger(item.price * line.quantity)
                              ? money(item.price * line.quantity)
                              : "—"}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <div className="cart-summary">
                  <div>
                    <span>Итого</span>
                    <strong>{total === null ? "—" : money(total)}</strong>
                  </div>
                  <p>
                    {total === null
                      ? "Проверьте доступность блюд и количество. Сумма заказа пока не подтверждена."
                      : "Цены могут измениться. Итоговую сумму нужно подтвердить перед заказом."}
                  </p>
                </div>
                <button
                  className="clear-cart"
                  onClick={() => {
                    setCart([]);
                    setNotice("Корзина очищена");
                  }}
                >
                  Очистить корзину
                </button>
              </>
            )}
            <CheckoutPanel
              cart={cart}
              total={total}
              onComplete={(intent) => {
                setCart((current) => {
                  const lines = current
                    .map((line) => ({
                      menu_item_id: line.id,
                      quantity: line.quantity,
                    }))
                    .sort((a, b) =>
                      a.menu_item_id.localeCompare(b.menu_item_id),
                    );
                  return JSON.stringify(lines) ===
                    JSON.stringify(intent.body.items)
                    ? []
                    : current;
                });
              }}
            />
            <div className="cart-storage">
              <Check size={14} aria-hidden="true" />
              <span>
                {storageWarning || "Выбор сохраняется в этом браузере"}
              </span>
            </div>
          </aside>
        </div>
        <div hidden={view !== "orders"} className="orders-screen">
          <a className="back-link" href="#cart">
            ← К корзине
          </a>
          <OrdersPanel />
        </div>
        <div hidden={view !== "profile"}>
          <ProfilePanel />
        </div>
        <div className="sr-only" role="status" aria-live="polite">
          {notice}
        </div>
        {notice && (
          <p className="action-notice" role="note">
            {notice}
          </p>
        )}
      </main>
      <nav className="bottom-nav" aria-label="Основная навигация">
        {(
          [
            { id: "venue", label: "Столовые", icon: MapPin },
            { id: "menu", label: "Меню", icon: Utensils },
            { id: "cart", label: "Заказ", icon: Ticket },
            { id: "profile", label: "Профиль", icon: UserRound },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <a
            key={id}
            href={`#${id}`}
            aria-current={
              view === id || (id === "cart" && view === "orders")
                ? "page"
                : undefined
            }
          >
            <Icon size={21} />
            <span>
              {label}
              {id === "cart" && quantity > 0 ? ` · ${quantity}` : ""}
            </span>
          </a>
        ))}
      </nav>
      {selectedDish && (
        <DishDetails
          item={selectedDish}
          onClose={() => setSelectedDish(null)}
          onAdd={() => {
            add(selectedDish);
            setSelectedDish(null);
          }}
        />
      )}
    </div>
  );
}

function QuantityControl({
  name,
  value,
  onChange,
  disabled = false,
}: {
  name: string;
  value: number;
  onChange: (next: number) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className="quantity-control"
      role="group"
      aria-label={`Количество: ${name}`}
    >
      <button
        aria-label={`Уменьшить количество: ${name}`}
        onClick={() => onChange(value - 1)}
      >
        <Minus size={16} aria-hidden="true" />
      </button>
      <span aria-live="polite">{value}</span>
      <button
        aria-label={`Увеличить количество: ${name}`}
        onClick={() => onChange(value + 1)}
        disabled={disabled || value >= MAX_INTEGER}
      >
        <Plus size={16} aria-hidden="true" />
      </button>
    </div>
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

function DishDetails({
  item,
  onClose,
  onAdd,
}: {
  item: MenuItem;
  onClose: () => void;
  onAdd: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="dish-dialog"
      onClose={onClose}
      aria-labelledby="dish-detail-title"
    >
      <button
        className="dialog-close"
        aria-label="Закрыть блюдо"
        onClick={onClose}
      >
        <X size={22} />
      </button>
      <DishPhoto item={item} />
      <h2 id="dish-detail-title">{item.name}</h2>
      <p className="dish-detail-price">{money(item.price)}</p>
      {item.description && <p>{item.description}</p>}
      <button className="primary-button" onClick={onAdd}>
        Добавить в корзину · {money(item.price)}
      </button>
    </dialog>
  );
}
