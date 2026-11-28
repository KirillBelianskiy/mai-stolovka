"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Ellipsis, Minus, Plus, X } from "lucide-react";
import { useState } from "react";
import { BottomAction, Sheet } from "@/components/customer-ui";
import { DishPhoto } from "@/components/dish-photo";
import { availablePortions, loadItem, MAX_INTEGER, money, type MenuItem } from "@/lib/menu";

export function DishDetails({ item, onBack, onSetQuantity, onCart, inCart, feedback }: {
  item: MenuItem;
  onBack: () => void;
  onSetQuantity: (item: MenuItem, count: number) => boolean;
  onCart: () => void;
  inCart: number;
  feedback: string;
}) {
  const detail = useQuery({
    queryKey: ["menu-item", item.id],
    queryFn: ({ signal }) => loadItem(item.id, signal),
    refetchOnMount: "always",
    retry: 1,
  });
  const [draft, setDraft] = useState<number | null>(null);
  const [about, setAbout] = useState(false);
  const count = draft ?? Math.max(1, inCart);
  const current = detail.data ?? item;
  const description = detail.data?.description?.trim();
  const descriptionIsLong = Boolean(description && description.length > 100);
  const maxCount = Math.min(availablePortions(current), current.price ? Math.floor(Number.MAX_SAFE_INTEGER / current.price) : MAX_INTEGER);
  const amount = money(current.price * count);
  const unavailable = detail.isError || availablePortions(current) === 0;
  const removing = count === 0;
  const actionLabel = removing ? "Убрать из корзины" : inCart ? "Обновить количество" : "Добавить в корзину";
  return (
    <section className="scene dish-scene" aria-labelledby="dish-heading">
      <div className="dish-artwork" aria-hidden="true">
        <DishPhoto item={current} detail eager />
      </div>
      <header className="dish-header">
        <button className="round-button" aria-label="Закрыть блюдо" onClick={onBack}><X aria-hidden="true" /></button>
        <h1 id="dish-heading">{current.name}</h1>
        {description && (
          <button className="round-button" aria-label="О блюде" onClick={() => setAbout(true)}>
            <Ellipsis aria-hidden="true" />
          </button>
        )}
      </header>
      <div className="dish-copy">
        {description && (!descriptionIsLong ? <p>{description}</p> : <p className="dish-description-preview">{description}</p>)}
      </div>
      <BottomAction>
        {(inCart > 0 || unavailable || detail.isPending || count > maxCount || feedback) && (
          <div className="purchase-feedback">
            {detail.isPending && <p role="status">Загружаем блюдо…</p>}
            {unavailable && (
              <p role="status">
                {detail.isError ? "Не удалось проверить блюдо." : current.remaining_quantity === 0 ? "Блюдо закончилось." : "Сейчас блюдо недоступно."}{" "}
                {detail.isError && <button className="text-button" onClick={() => void detail.refetch()}>Повторить</button>}
              </p>
            )}
            {!unavailable && count > maxCount && <p>Уменьшите количество порций.</p>}
            {feedback && <p role="status">{feedback}</p>}
            {inCart > 0 && <button className="text-button" onClick={onCart}>В корзине · {inCart}</button>}
          </div>
        )}
        <div className="purchase-dock">
          <div className="quantity-control" role="group" aria-label="Количество порций">
            <button aria-label="Уменьшить количество" disabled={count <= (inCart ? 0 : 1)} onClick={() => setDraft(count - 1)}>
              <Minus size={18} aria-hidden="true" />
            </button>
            <span aria-live="polite">{count}</span>
            <button aria-label="Увеличить количество" disabled={count >= maxCount || unavailable} onClick={() => setDraft(count + 1)}>
              <Plus size={18} aria-hidden="true" />
            </button>
          </div>
          <button className="primary-button"
            aria-label={removing ? actionLabel : actionLabel + ": " + current.name + ", количество " + count + ", " + amount}
            onClick={() => { if (onSetQuantity(current, count)) setDraft(null); }}
            disabled={count === inCart || (!removing && (detail.isFetching || unavailable || count > maxCount))}>
            {removing ? actionLabel : <>{inCart ? <Check size={18} aria-hidden="true" /> : <Plus size={18} aria-hidden="true" />} {amount}</>}
          </button>
        </div>
      </BottomAction>
      {about && <Sheet title="О блюде" onDismiss={() => setAbout(false)}><p>{description}</p></Sheet>}
    </section>
  );
}
