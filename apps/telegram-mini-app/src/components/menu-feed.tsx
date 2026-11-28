"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Plus, Send, UserRound } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type TouchEvent } from "react";
import { PromoCover } from "@/components/promo-cover";
import { CAMPUS } from "@/components/customer-ui";
import { DishPhoto } from "@/components/dish-photo";
import {
  availablePortions, loadCategories, loadItems, money, type CartLine, type MenuItem,
} from "@/lib/menu";

type Position = {
  top: number;
  anchor: string | undefined;
  offset: number;
  shelves: Record<string, number>;
};

type Swipe = {
  x: number;
  y: number;
  time: number;
  axis: "horizontal" | "vertical" | null;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
}

type Props = {
  active: boolean;
  openDish: (item: MenuItem) => void;
  openProfile: () => void;
  cart: CartLine[];
  canAdd: boolean;
  add: (item: MenuItem) => boolean;
  feedback: string;
  dock: ReactNode;
};

export function MenuFeed({ active, openDish, openProfile, cart, canAdd, add, feedback, dock }: Props) {
  const [category, setCategory] = useState<string | null>(null);
  const feed = useRef<HTMLElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const hero = useRef<HTMLDivElement>(null);
  const rail = useRef<HTMLElement>(null);
  const profile = useRef<HTMLButtonElement>(null);
  const positions = useRef(new Map<string | null, Position>());
  const pendingPosition = useRef<Position | null>(null);
  const returnFocus = useRef<string | "profile" | null>(null);
  const gesture = useRef<Swipe | null>(null);
  const categories = useQuery({
    queryKey: ["menu-categories"],
    queryFn: ({ signal }) => loadCategories(signal), retry: 1, refetchInterval: active ? 30000 : false,
  });
  const menu = useInfiniteQuery({
    queryKey: ["menu-items", category],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => loadItems(category, pageParam, signal),
    getNextPageParam: (page) =>
      page.items.length > 0 && page.offset + page.items.length < page.total
        ? page.offset + page.items.length
        : undefined,
    gcTime: Infinity,
    staleTime: 30000,
    refetchInterval: active ? 30000 : false,
    retry: 1,
  });
  const items = [
    ...new Map(menu.data?.pages.flatMap((page) => page.items).map((item) => [item.id, item])).values(),
  ];
  const options = [{ id: null, name: "На обед" }, ...(categories.data ?? []).filter((entry) => entry.published_item_count !== 0)];
  const featured = items.filter((item) => item.is_available).slice(0, 3);
  const sections = (categories.data ?? []).flatMap(({ id, name }) => {
    const matching = items.filter((item) => item.category_id === id);
    return matching.length ? [{ id, name, items: matching }] : [];
  });
  const unsorted = items.filter((item) => !categories.data?.some(({ id }) => id === item.category_id));
  if (unsorted.length) sections.push({ id: "catalog", name: "Меню", items: unsorted });
  const filterTitle = categories.data?.find(({ id }) => id === category)?.name ?? "Меню";

  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } = menu;
  useEffect(() => {
    if (!active || !hasNextPage || isFetching || isFetchNextPageError || !sentinel.current ||
      !feed.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void fetchNextPage({ cancelRefetch: false });
    }, { root: feed.current, rootMargin: "160px 0px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [active, hasNextPage, isFetching, isFetchNextPageError, fetchNextPage, category]);

  function recordPosition(): Position | null {
    const viewport = feed.current;
    if (!viewport) return null;
    const left = viewport.getBoundingClientRect().left;
    const right = viewport.getBoundingClientRect().right;
    const top = viewport.getBoundingClientRect().top;
    const candidates = [...viewport.querySelectorAll<HTMLElement>("[data-feed-card]")];
    const anchor = candidates.find((card) => {
      const rect = card.getBoundingClientRect();
      return rect.bottom > top && rect.right > left && rect.left < right;
    });
    const shelves = Object.fromEntries(
      [...viewport.querySelectorAll<HTMLElement>("[data-scroll-key]")].map(
        (shelf) => [shelf.dataset.scrollKey!, shelf.scrollLeft],
      ),
    );
    return {
      top: viewport.scrollTop,
      anchor: anchor?.dataset.feedCard,
      offset: anchor?.getBoundingClientRect().top ?? 0,
      shelves,
    };
  }

  function switchCategory(id: string | null) {
    if (id === category) return;
    // A pending tab may still be showing a short skeleton. Keep its saved position.
    const current = pendingPosition.current ?? recordPosition();
    if (!pendingPosition.current && current) positions.current.set(category, current);
    pendingPosition.current = positions.current.get(id) ?? {
      top: current?.top ?? 0, anchor: undefined, offset: 0, shelves: {},
    };
    setCategory(id);
  }

  function visit(key: string, action: () => void) {
    const position = recordPosition();
    if (position) positions.current.set(category, position);
    returnFocus.current = key;
    action();
  }

  useLayoutEffect(() => {
    if (!active || !feed.current) return;
    const viewport = feed.current;
    const position = pendingPosition.current ?? (returnFocus.current ? positions.current.get(category) : null);
    if (position && menu.isPending) {
      viewport.scrollTop = position.top;
    }
    if (position && !menu.isPending) {
      for (const shelf of viewport.querySelectorAll<HTMLElement>("[data-scroll-key]")) {
        const saved = position.shelves[shelf.dataset.scrollKey!];
        if (saved !== undefined) shelf.scrollLeft = saved;
      }
      viewport.scrollTop = position.top;
      if (position.anchor && position.top > (hero.current?.offsetHeight ?? 0) / 2) {
        const anchor = [...viewport.querySelectorAll<HTMLElement>("[data-feed-card]")]
          .find((card) => card.dataset.feedCard === position.anchor);
        if (anchor) viewport.scrollTop += anchor.getBoundingClientRect().top - position.offset;
      }
      pendingPosition.current = null;
    }
    if (returnFocus.current && !menu.isPending) {
      const key = returnFocus.current;
      const cards = [...viewport.querySelectorAll<HTMLElement>("[data-feed-card]")];
      const picked = key === "profile" ? profile.current : cards.find((card) => card.dataset.feedCard === key);
      const nearest = cards.find((card) => card.getBoundingClientRect().bottom > (rail.current?.getBoundingClientRect().bottom ?? 0));
      (picked ?? nearest ?? viewport.querySelector<HTMLElement>("#menu-heading"))?.focus({ preventScroll: true });
      returnFocus.current = null;
    }
    if (rail.current) {
      const pressed = rail.current.querySelector("button[aria-pressed='true']");
      if (pressed instanceof HTMLElement) {
        const strip = rail.current;
        const button = pressed.getBoundingClientRect();
        const bounds = strip.getBoundingClientRect();
        if (button.right > bounds.right) strip.scrollLeft += button.right - bounds.right + 16;
        if (button.left < bounds.left) strip.scrollLeft += button.left - bounds.left - 16;
      }
    }
  }, [active, category, menu.isPending, menu.data]);

  function startSwipe(event: TouchEvent) {
    const target = event.target;
    const touch = event.touches[0];
    const edge = feed.current?.getBoundingClientRect();
    gesture.current = event.touches.length === 1 && edge && touch.clientX > edge.left + 16 &&
      touch.clientX < edge.right - 16 && target instanceof Element &&
      !target.closest("[data-scroll-key], [data-promo-carousel], button:not(.food-card-body), a, input")
      ? { x: touch.clientX, y: touch.clientY, time: event.timeStamp, axis: null }
      : null;
  }

  function trackSwipe(event: TouchEvent) {
    const start = gesture.current;
    if (!start) return;
    if (event.touches.length !== 1) {
      gesture.current = null;
      return;
    }
    if (start.axis) return;

    const touch = event.touches[0];
    const dx = Math.abs(touch.clientX - start.x);
    const dy = Math.abs(touch.clientY - start.y);
    if (Math.hypot(dx, dy) >= 18) {
      start.axis = dx >= dy * 1.5 ? "horizontal" : "vertical";
    }
  }

  function finishSwipe(event: TouchEvent) {
    const start = gesture.current;
    gesture.current = null;
    if (!start || start.axis === "vertical" || event.touches.length !== 0) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    const distance = Math.abs(dx);
    const width = feed.current?.clientWidth ?? 390;
    const speed = distance / Math.max(1, event.timeStamp - start.time);
    const crossed = distance >= clamp(width * .2, 56, 88);
    const flicked = distance >= clamp(width * .1, 34, 52) && speed >= .45;
    if (distance < Math.abs(dy) * 1.7 || (!crossed && !flicked)) return;
    const index = options.findIndex(({ id }) => id === category);
    const next = options[index + (dx < 0 ? 1 : -1)];
    if (next) switchCategory(next.id);
  }

  const shelf = (id: string, list: MenuItem[], compact = false) => (
    <div className={compact ? "food-shelf featured-shelf" : category ? "category-grid" : "food-shelf catalog-shelf"} data-scroll-key={category ? undefined : id}>
      {list.map((item) => {
        const count = cart.find((line) => line.id === item.id)?.quantity ?? 0;
        const key = id + "/" + item.id;
        return (
          <article className="food-card" data-sold-out={availablePortions(item) === 0} key={item.id}>
            <button className="food-card-body" data-feed-card={key}
              aria-label={"Подробнее: " + item.name + ", " + money(item.price)}
              onClick={() => visit(key, () => openDish(item))}>
              <DishPhoto item={item} />
              <strong>{item.name}</strong>
              <span>{money(item.price)}</span>
            </button>
            <button className="food-card-add"
              aria-label={"Добавить " + item.name + " в корзину" + (count ? ", в корзине " + count : "")}
              disabled={!canAdd || count >= availablePortions(item)}
              onClick={() => add(item)}
            >
              <span>{count || <Plus size={16} aria-hidden="true" />}</span>
            </button>
            {availablePortions(item) === 0 && <p className="food-unavailable">Закончилось</p>}
          </article>
        );
      })}
    </div>
  );

  return (
    <div className="menu-view" hidden={!active}>
      <section ref={feed} className={"menu-feed" + (dock ? " has-dock" : "")} aria-label="Меню столовой"
        onTouchStart={startSwipe} onTouchMove={trackSwipe} onTouchEnd={finishSwipe}
        onTouchCancel={() => { gesture.current = null; }}>
        <div ref={hero} className="menu-cover">
          <PromoCover active={active} />
          <header className="menu-header">
            <Send size={29} strokeWidth={1.5} aria-hidden="true" />
            <div><strong>{CAMPUS}</strong>
              <button ref={profile} className="round-button" aria-label="Профиль"
                onClick={() => visit("profile", openProfile)}>
                <UserRound size={22} aria-hidden="true" />
              </button>
            </div>
          </header>
        </div>
        <nav ref={rail} data-scroll-key="categories" className="category-rail" aria-label="Категории блюд">
          {options.map(({ id, name }) => (
            <button key={id ?? "all"} aria-pressed={id === category} onClick={() => switchCategory(id)}>
              {name}
            </button>
          ))}
        </nav>
        <div className="feed-content">
          <h1 id="menu-heading" tabIndex={-1}>{category === null ? "Что на обед?" : filterTitle}</h1>
          {categories.isError && (
            <div className="feed-feedback" role="status">
              Категории пока недоступны.
              <button className="text-button" onClick={() => void categories.refetch()}>Повторить загрузку категорий</button>
            </div>
          )}
          {feedback && <p className="feed-feedback" role="status">{feedback}</p>}
          {menu.isPending ? (
            <div role="status" aria-label="Загружаем меню" className="shelf-skeleton">
              <span /><span /><span />
            </div>
          ) : menu.isError && !items.length ? (
            <div className="feed-state" role="alert">
              <div className="state-art plane-art" />
              <h2>Меню не загрузилось</h2>
              <button className="primary-button" onClick={() => void menu.refetch()}>Повторить</button>
            </div>
          ) : items.length === 0 ? (
            <div className="feed-state">
              <p>{category ? "Сейчас блюд этой категории нет." : "Сейчас в меню нет блюд."}</p>
            </div>
          ) : category === null ? (
            <>
              {featured.length > 0 && shelf("featured", featured, true)}
              {sections.map((section) => (
                <section className="food-section" key={section.id}>
                  <h2>{section.name}</h2>
                  {shelf(section.id, section.items)}
                </section>
              ))}
            </>
          ) : shelf(category, items)}
          {menu.isError && items.length > 0 && (
            <p role="alert">Не удалось обновить меню.{" "}
              <button className="text-button" onClick={() => void (menu.isFetchNextPageError ? menu.fetchNextPage() : menu.refetch())}>Повторить</button>
            </p>
          )}
          {menu.hasNextPage && <div ref={sentinel} className="menu-page-marker" role="status">
            {menu.isFetchingNextPage && "Загружаем блюда…"}
          </div>}
        </div>
      </section>
      {dock}
    </div>
  );
}
