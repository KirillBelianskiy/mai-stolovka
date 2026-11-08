"use client";

import { Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  apiRequest,
  ApiError,
  type StaffSession,
} from "@/lib/kitchen";

type Category = { id: string; name: string; sort_order: number };
type MenuItem = {
  id: string;
  category_id: string;
  name: string;
  description: string | null;
  price: number;
  image_url: string | null;
  is_available: boolean;
};
type TimeSlot = {
  id: string;
  start_time: string;
  end_time: string;
  capacity: number;
  current_orders: number;
};
type Notice = { kind: "error" | "success"; text: string };
type AdminData = { categories: Category[]; items: MenuItem[]; slots: TimeSlot[] };
type MenuItemForm = {
  category_id: string;
  name: string;
  description: string;
  price: string;
  image_url: string;
  is_available: boolean;
};
type SlotForm = { date: string; start: string; end: string; capacity: string };

const EMPTY_ITEM: MenuItemForm = {
  category_id: "",
  name: "",
  description: "",
  price: "",
  image_url: "",
  is_available: true,
};

function moscowDate(value: string): string {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function moscowTime(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatMoscow(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function nextWeekday(): string {
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const moscow = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(tomorrow);
  const [year, month, day] = moscow.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6) {
    date.setUTCDate(date.getUTCDate() + 1);
  }
  return [date.getUTCFullYear(), String(date.getUTCMonth() + 1).padStart(2, "0"), String(date.getUTCDate()).padStart(2, "0")].join("-");
}

function isWeekday(date: string): boolean {
  const [year, month, day] = date.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return weekday !== 0 && weekday !== 6;
}

function toMoscowIso(date: string, time: string): string {
  return new Date(`${date}T${time}:00+03:00`).toISOString();
}

function toKopecks(value: string): number {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) {
    throw new Error("Укажите цену в рублях, например 125 или 125,50.");
  }
  const [rubles, kopecks = ""] = normalized.split(".");
  const amount = Number(rubles) * 100 + Number(kopecks.padEnd(2, "0"));
  if (!Number.isSafeInteger(amount) || amount > 2_147_483_647) {
    throw new Error("Цена превышает допустимое значение.");
  }
  return amount;
}

function responseMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) {
    return "Недостаточно прав. Изменения доступны только администратору.";
  }
  if (error instanceof ApiError && error.status === 409) {
    return `${error.message} Обновите данные и проверьте связанные заказы.`;
  }
  return error instanceof Error ? error.message : "Не удалось выполнить действие.";
}

function displayPrice(kopecks: number): string {
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(kopecks / 100);
}

export function AdminPanel({
  session,
  onUnauthorized,
}: {
  session: StaffSession;
  onUnauthorized: () => void;
}) {
  const [data, setData] = useState<AdminData>({ categories: [], items: [], slots: [] });
  const [notice, setNotice] = useState<Notice | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [categoryName, setCategoryName] = useState("");
  const [categorySortOrder, setCategorySortOrder] = useState("0");
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [itemForm, setItemForm] = useState<MenuItemForm>(EMPTY_ITEM);
  const [editingItem, setEditingItem] = useState<string | null>(null);
  const [slotForm, setSlotForm] = useState<SlotForm>({
    date: nextWeekday(),
    start: "11:00",
    end: "11:30",
    capacity: "30",
  });
  const [editingSlot, setEditingSlot] = useState<string | null>(null);

  const load = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    try {
      const [categories, itemPage, slots] = await Promise.all([
        apiRequest<Category[]>("/menu/categories", session.token),
        apiRequest<{ items: MenuItem[] }>("/menu/admin/items?limit=100", session.token),
        apiRequest<TimeSlot[]>("/orders/slots?include_past=true&limit=100", session.token),
      ]);
      setData({ categories, items: itemPage.items, slots });
      setNotice(null);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized();
      setNotice({ kind: "error", text: responseMessage(error) });
      return false;
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized, session.token]);

  useEffect(() => { void load(); }, [load]);

  if (session.user.role !== "ADMIN") {
    return <div className="admin-denied" role="alert">Управление меню и слотами доступно только администратору.</div>;
  }

  async function refreshAfter(action: () => Promise<unknown>, success: string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setNotice(null);
    try {
      await action();
      if (!(await load())) return false;
      setNotice({ kind: "success", text: success });
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized();
      setNotice({ kind: "error", text: responseMessage(error) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function saveCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = categoryName.trim();
    const sort_order = Number(categorySortOrder);
    if (!name || !Number.isInteger(sort_order)) {
      setNotice({ kind: "error", text: "Укажите название и целый порядок сортировки." });
      return;
    }
    const body = JSON.stringify({ name, sort_order });
    const path = editingCategory ? `/menu/categories/${editingCategory}` : "/menu/categories";
    const saved = await refreshAfter(
      () => apiRequest(path, session.token, { method: editingCategory ? "PUT" : "POST", body }),
      editingCategory ? "Категория обновлена." : "Категория создана.",
    );
    if (!saved) return;
    setCategoryName("");
    setCategorySortOrder("0");
    setEditingCategory(null);
  }

  async function removeCategory(category: Category) {
    if (!window.confirm(`Удалить категорию «${category.name}»?`)) return;
    await refreshAfter(
      () => apiRequest(`/menu/categories/${category.id}`, session.token, { method: "DELETE" }),
      "Категория удалена.",
    );
  }

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const price = toKopecks(itemForm.price);
      if (!itemForm.category_id) throw new Error("Выберите категорию.");
      const body = JSON.stringify({
        category_id: itemForm.category_id,
        name: itemForm.name.trim(),
        description: itemForm.description.trim() || null,
        price,
        image_url: itemForm.image_url.trim() || null,
        is_available: itemForm.is_available,
      });
      const path = editingItem ? `/menu/items/${editingItem}` : "/menu/items";
      const saved = await refreshAfter(
        () => apiRequest(path, session.token, { method: editingItem ? "PUT" : "POST", body }),
        editingItem ? "Блюдо обновлено." : "Блюдо создано.",
      );
      if (!saved) return;
      setItemForm(EMPTY_ITEM);
      setEditingItem(null);
    } catch (error) {
      setNotice({ kind: "error", text: responseMessage(error) });
    }
  }

  function editItem(item: MenuItem) {
    setEditingItem(item.id);
    setItemForm({
      category_id: item.category_id,
      name: item.name,
      description: item.description ?? "",
      price: `${Math.floor(item.price / 100)}.${String(item.price % 100).padStart(2, "0")}`,
      image_url: item.image_url ?? "",
      is_available: item.is_available,
    });
    document.getElementById("item-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function removeItem(item: MenuItem) {
    if (!window.confirm(`Удалить блюдо «${item.name}»? Заказы с историей блюда защищены сервером.`)) return;
    await refreshAfter(
      () => apiRequest(`/menu/items/${item.id}`, session.token, { method: "DELETE" }),
      "Блюдо удалено.",
    );
  }

  async function saveSlot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (!isWeekday(slotForm.date)) throw new Error("Столовая работает по будням в часовом поясе Europe/Moscow.");
      const start_time = toMoscowIso(slotForm.date, slotForm.start);
      const end_time = toMoscowIso(slotForm.date, slotForm.end);
      if (new Date(start_time).getTime() <= Date.now()) throw new Error("Начало слота должно быть в будущем.");
      if (new Date(start_time).getTime() >= new Date(end_time).getTime()) {
        throw new Error("Окончание слота должно быть позже начала.");
      }
      const capacity = Number(slotForm.capacity);
      if (!Number.isInteger(capacity) || capacity < 1 || capacity > 2_147_483_647) {
        throw new Error("Вместимость должна быть положительным целым числом.");
      }
      const currentOrders = data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 0;
      if (capacity < currentOrders) throw new Error("Вместимость не может быть меньше числа существующих заказов.");
      const body = JSON.stringify({ start_time, end_time, capacity });
      const path = editingSlot ? `/orders/slots/${editingSlot}` : "/orders/slots";
      const saved = await refreshAfter(
        () => apiRequest(path, session.token, { method: editingSlot ? "PUT" : "POST", body }),
        editingSlot ? "Слот обновлён." : "Слот создан.",
      );
      if (!saved) return;
      setEditingSlot(null);
      setSlotForm({ ...slotForm, date: nextWeekday() });
    } catch (error) {
      setNotice({ kind: "error", text: responseMessage(error) });
    }
  }

  function editSlot(slot: TimeSlot) {
    setEditingSlot(slot.id);
    setSlotForm({
      date: moscowDate(slot.start_time),
      start: moscowTime(slot.start_time),
      end: moscowTime(slot.end_time),
      capacity: String(slot.capacity),
    });
    document.getElementById("slot-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function removeSlot(slot: TimeSlot) {
    if (slot.current_orders > 0) {
      setNotice({ kind: "error", text: "В слоте есть заказы. Сервер запрещает его удаление." });
      return;
    }
    if (!window.confirm(`Удалить слот ${formatMoscow(slot.start_time)}?`)) return;
    await refreshAfter(
      () => apiRequest(`/orders/slots/${slot.id}`, session.token, { method: "DELETE" }),
      "Слот удалён.",
    );
  }

  return (
    <div className="admin-panel">
      {notice && (
        <div className={`alert ${notice.kind === "error" ? "alert-error" : "alert-success"}`} role={notice.kind === "error" ? "alert" : "status"}>
          <span>{notice.text}</span>
          <button aria-label="Скрыть сообщение" className="icon-button" onClick={() => setNotice(null)} type="button"><X size={16} /></button>
        </div>
      )}
      <div className="admin-panel-heading">
        <div><p className="eyebrow">УПРАВЛЕНИЕ</p><h2>Меню и расписание</h2></div>
        <button className="secondary-button" disabled={loading || busy} onClick={() => void load()} type="button">
          <RefreshCw size={15} /> Обновить данные
        </button>
      </div>
      <p className="admin-timezone-note">Даты отображаются по Москве (UTC+3). Слоты доступны по будням; точное время обслуживания настраивается оператором.</p>

      <section className="admin-section">
        <div className="admin-section-heading"><div><h3>Категории</h3><p>Категории группируют блюда в меню.</p></div></div>
        <form className="admin-inline-form category-form" onSubmit={saveCategory}>
          <label>Название<input maxLength={128} onChange={(event) => setCategoryName(event.target.value)} required value={categoryName} /></label>
          <label>Порядок<input max={2147483647} min={-2147483648} onChange={(event) => setCategorySortOrder(event.target.value)} step="1" type="number" value={categorySortOrder} /></label>
          <button className="primary-button" disabled={busy} type="submit"><Save size={15} />{editingCategory ? "Сохранить" : "Добавить"}</button>
          {editingCategory && <button className="secondary-button" onClick={() => { setEditingCategory(null); setCategoryName(""); setCategorySortOrder("0"); }} type="button">Отмена</button>}
        </form>
        <div className="admin-list">
          {data.categories.map((category) => (
            <div className="admin-list-row" key={category.id}>
              <div><strong>{category.name}</strong><small>Порядок: {category.sort_order}</small></div>
              <div className="admin-row-actions">
                <button className="text-button" onClick={() => { setEditingCategory(category.id); setCategoryName(category.name); setCategorySortOrder(String(category.sort_order)); }} type="button">Изменить</button>
                <button aria-label={`Удалить ${category.name}`} className="icon-button danger-icon" disabled={busy} onClick={() => void removeCategory(category)} type="button"><Trash2 size={16} /></button>
              </div>
            </div>
          ))}
          {!loading && data.categories.length === 0 && <p className="admin-empty">Категорий пока нет.</p>}
        </div>
      </section>

      <section className="admin-section">
        <div className="admin-section-heading"><div><h3>{editingItem ? "Изменить блюдо" : "Блюда"}</h3><p>Цена вводится в рублях, сервер хранит копейки.</p></div></div>
        <form className="admin-item-form" id="item-form" onSubmit={saveItem}>
          <label>Название<input maxLength={256} onChange={(event) => setItemForm({ ...itemForm, name: event.target.value })} required value={itemForm.name} /></label>
          <label>Категория<select onChange={(event) => setItemForm({ ...itemForm, category_id: event.target.value })} required value={itemForm.category_id}><option value="">Выберите категорию</option>{data.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
          <label>Цена, ₽<input inputMode="decimal" onChange={(event) => setItemForm({ ...itemForm, price: event.target.value })} placeholder="Например, 125,50" required value={itemForm.price} /></label>
          <label>Ссылка на изображение<input maxLength={2048} onChange={(event) => setItemForm({ ...itemForm, image_url: event.target.value })} type="url" value={itemForm.image_url} /></label>
          <label className="span-all">Описание<textarea maxLength={10000} onChange={(event) => setItemForm({ ...itemForm, description: event.target.value })} rows={2} value={itemForm.description} /></label>
          {editingItem && <label className="availability-control"><input checked={itemForm.is_available} onChange={(event) => setItemForm({ ...itemForm, is_available: event.target.checked })} type="checkbox" /> Доступно покупателям</label>}
          <div className="form-actions span-all">
            <button className="primary-button" disabled={busy || data.categories.length === 0} type="submit"><Save size={15} />{editingItem ? "Сохранить блюдо" : "Добавить блюдо"}</button>
            {editingItem && <button className="secondary-button" onClick={() => { setEditingItem(null); setItemForm(EMPTY_ITEM); }} type="button">Отмена</button>}
          </div>
        </form>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Блюдо</th><th>Категория</th><th>Цена</th><th>Доступность</th><th><span className="sr-only">Действия</span></th></tr></thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</td>
                  <td>{data.categories.find((category) => category.id === item.category_id)?.name ?? "Категория удалена"}</td>
                  <td>{displayPrice(item.price)}</td>
                  <td><span className={item.is_available ? "availability available" : "availability unavailable"}>{item.is_available ? "В меню" : "Скрыто"}</span></td>
                  <td><div className="admin-row-actions"><button className="text-button" onClick={() => editItem(item)} type="button">Изменить</button><button aria-label={`Удалить ${item.name}`} className="icon-button danger-icon" disabled={busy} onClick={() => void removeItem(item)} type="button"><Trash2 size={16} /></button></div></td>
                </tr>
              ))}
              {!loading && data.items.length === 0 && <tr><td className="admin-empty" colSpan={5}>Блюд пока нет.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-section">
        <div className="admin-section-heading"><div><h3>{editingSlot ? "Изменить слот" : "Слоты выдачи"}</h3><p>Будни, Europe/Moscow. Часы обслуживания задаёт оператор.</p></div></div>
        <form className="admin-inline-form slot-form" id="slot-form" onSubmit={saveSlot}>
          <label>Дата (МСК)<input disabled={(data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 0) > 0} onChange={(event) => setSlotForm({ ...slotForm, date: event.target.value })} required type="date" value={slotForm.date} /></label>
          <label>Начало (МСК)<input disabled={(data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 0) > 0} onChange={(event) => setSlotForm({ ...slotForm, start: event.target.value })} required type="time" value={slotForm.start} /></label>
          <label>Окончание (МСК)<input disabled={(data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 0) > 0} onChange={(event) => setSlotForm({ ...slotForm, end: event.target.value })} required type="time" value={slotForm.end} /></label>
          <label>Вместимость<input min={editingSlot ? data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 1 : 1} onChange={(event) => setSlotForm({ ...slotForm, capacity: event.target.value })} required step="1" type="number" value={slotForm.capacity} /></label>
          <button className="primary-button" disabled={busy} type="submit"><Plus size={15} />{editingSlot ? "Сохранить" : "Создать слот"}</button>
          {editingSlot && <button className="secondary-button" onClick={() => { setEditingSlot(null); setSlotForm({ ...slotForm, date: nextWeekday() }); }} type="button">Отмена</button>}
        </form>
        {(data.slots.find((slot) => slot.id === editingSlot)?.current_orders ?? 0) > 0 && (
          <p className="admin-inline-note">Время слота нельзя менять: в нём уже есть заказы. Вместимость можно увеличить или оставить без изменений.</p>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table slots-table">
            <thead><tr><th>Время (МСК)</th><th>Свободно</th><th>Заказов</th><th><span className="sr-only">Действия</span></th></tr></thead>
            <tbody>
              {data.slots.map((slot) => (
                <tr key={slot.id}>
                  <td>{formatMoscow(slot.start_time)}–{moscowTime(slot.end_time)}</td>
                  <td>{slot.capacity - slot.current_orders} / {slot.capacity}</td>
                  <td>{slot.current_orders}</td>
                  <td><div className="admin-row-actions"><button className="text-button" onClick={() => editSlot(slot)} type="button">Изменить</button><button aria-label="Удалить слот" className="icon-button danger-icon" disabled={busy || slot.current_orders > 0} onClick={() => void removeSlot(slot)} type="button"><Trash2 size={16} /></button></div></td>
                </tr>
              ))}
              {!loading && data.slots.length === 0 && <tr><td className="admin-empty" colSpan={4}>Слотов пока нет.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {loading && <p className="admin-loading">Обновляем данные…</p>}
    </div>
  );
}
