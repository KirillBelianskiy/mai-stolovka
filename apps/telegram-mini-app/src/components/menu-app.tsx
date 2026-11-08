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
  ShoppingBag,
  Soup,
  Trash2,
  UtensilsCrossed,
} from "lucide-react";
import { CheckoutPanel, OrdersPanel } from "@/components/order-workspace";
import { ProfilePanel } from "@/components/profile-panel";
import { useEffect, useState } from "react";
import {
  CART_KEY,
  MAX_INTEGER,
  addToCart,
  cartTotal,
  decodeCart,
  imageUrl,
  loadCategories,
  loadItem,
  loadItems,
  money,
  saveCart,
  setQuantity,
  type CartLine,
  type MenuItem,
} from "@/lib/menu";

export function MenuApp() {
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
  const categoryName =
    categories.data?.find((value) => value.id === category)?.name ?? "Всё меню";

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
        <a href="#" className="wordmark" aria-label="МАИ Еда — к началу">
          <span className="brand-symbol">
            <UtensilsCrossed size={21} aria-hidden="true" />
          </span>
          <span>
            МАИ<span className="wordmark-light"> ЕДА</span>
          </span>
        </a>
        <nav aria-label="Основная навигация">
          <a href="#menu">Меню</a>
          <a href="#cart">
            Корзина{" "}
            <span className="nav-count">
              {quantity > 99 ? "99+" : quantity}
            </span>
          </a>
          <a href="#orders">Заказы</a>
          <a href="#profile">Профиль</a>
        </nav>
        <span className="header-note">Хороший обед — по плану.</span>
      </header>
      <main>
        <section className="menu-intro" aria-labelledby="page-heading">
          <div>
            <p className="eyebrow">
              <span className="small-rule" /> Столовая МАИ
            </p>
            <h1 id="page-heading">
              Обед в МАИ<span className="heading-dot">.</span>
            </h1>
            <p className="intro-copy">
              Любимые блюда.
              <br className="mobile-break" /> Соберите свой обед.
            </p>
          </div>
          <a className="intro-link" href="#menu">
            <span>Что на обед?</span>
            <ArrowDown size={20} aria-hidden="true" />
          </a>
        </section>

        <div className="menu-layout">
          <section
            id="menu"
            className="menu-section"
            aria-labelledby="menu-heading"
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">Выбирайте по вкусу</p>
                <h2 id="menu-heading">{categoryName}</h2>
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
            <div className="category-list" aria-label="Категории блюд">
              <button
                aria-pressed={category === null}
                onClick={() => setCategory(null)}
              >
                Всё меню
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
                {items.map((item, index) => (
                  <article className="dish-card" key={item.id}>
                    {imageUrl(item.image_url) && (
                      <div className="dish-photo">
                        <img
                          src={imageUrl(item.image_url)}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          onError={(event) => {
                            event.currentTarget.style.display = "none";
                          }}
                        />
                      </div>
                    )}
                    <div className="dish-meta">
                      <span>
                        {categories.data?.find(
                          (value) => value.id === item.category_id,
                        )?.name ?? "Блюдо"}
                      </span>
                      <span className="dish-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                    </div>
                    <h3>{item.name}</h3>
                    <p className="dish-description">
                      {item.description || "Приготовлено в нашей столовой."}
                    </p>
                    <div className="dish-bottom">
                      <span className="dish-price">{money(item.price)}</span>
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
                              <Plus size={18} aria-hidden="true" />
                              <span>Добавить</span>
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
            aria-labelledby="cart-heading"
          >
            <div className="cart-top">
              <span className="cart-icon">
                <ShoppingBag size={24} aria-hidden="true" />
              </span>
              <span className="cart-label">Собрано вами</span>
            </div>
            <div className="cart-title">
              <h2 id="cart-heading">Ваш обед</h2>
              <span>{String(cart.length).padStart(2, "0")}</span>
            </div>
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
                    <span>Предварительно</span>
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
        <OrdersPanel />
        <ProfilePanel />
        <div className="sr-only" role="status" aria-live="polite">
          {notice}
        </div>
        {notice && (
          <p className="action-notice" role="note">
            {notice}
          </p>
        )}
      </main>
      <footer className="app-footer">
        <span>МАИ ЕДА</span>
        <p>Выбирайте. Собирайте. Приятного аппетита.</p>
        <a href="#page-heading">К началу ↑</a>
      </footer>
      {cart.length > 0 && (
        <a className="mobile-cart-link" href="#cart">
          <span>
            <ShoppingBag size={18} aria-hidden="true" />
            Корзина{" "}
            <span className="mobile-cart-count">
              {quantity > 99 ? "99+" : quantity}
            </span>
          </span>
          <strong>
            {total === null ? "Проверить" : `≈ ${money(total)}`}
            <ArrowRight size={17} aria-hidden="true" />
          </strong>
        </a>
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
