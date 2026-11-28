"use client";

import { ChevronLeft, X } from "lucide-react";
import {
  createContext, useContext, useEffect, useRef, type ReactNode,
} from "react";

export const CAMPUS = "Ледокол";
export const ART = "/design/mai-eda";
export const BackContext = createContext<{ register: (dismiss: () => void) => () => void } | null>(null);

export function ScreenHeader({ onBack, label = "Назад" }: {
  onBack: () => void;
  label?: string;
}) {
  return (
    <header className="screen-header">
      <button type="button" className="round-button" aria-label={label} onClick={onBack}>
        <ChevronLeft aria-hidden="true" />
      </button>
      <span className="campus-pill">{CAMPUS}</span>
    </header>
  );
}

export function BottomAction({ children }: { children: ReactNode }) {
  return <div className="bottom-action">{children}</div>;
}

export function Sheet({ title, onDismiss, children, alert = false }: {
  title: string;
  onDismiss: () => void;
  children: ReactNode;
  alert?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const back = useContext(BackContext);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.showModal) {
      element.setAttribute("open", "");
      return;
    }
    element.showModal();
    return () => element.close();
  }, []);
  useEffect(() => back?.register(onDismiss), [back, onDismiss]);
  return (
    <dialog
      className="customer-sheet"
      ref={dialog}
      role={alert ? "alertdialog" : undefined}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onDismiss();
      }}
    >
      <header>
        <h2>{title}</h2>
        {!alert && (
          <button type="button" className="round-button" aria-label="Закрыть" onClick={onDismiss}>
            <X aria-hidden="true" />
          </button>
        )}
      </header>
      {children}
    </dialog>
  );
}

const date = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", day: "numeric", month: "long",
});
const dayKey = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Moscow", day: "numeric", month: "numeric", year: "numeric",
});
const time = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit",
});
const plurals = new Intl.PluralRules("ru-RU");

export function moscowDay(value: string | number) {
  return dayKey.format(new Date(value));
}

export function moscowDate(value: string) {
  return date.format(new Date(value));
}

export function pickupTime(start: string, end: string) {
  const endDay = moscowDay(start) === moscowDay(end) ? "" : moscowDate(end) + ", ";
  return time.format(new Date(start)) + "–" + endDay + time.format(new Date(end));
}

export function totalPortions(lines: ReadonlyArray<{ quantity: number }>) {
  return lines.reduce((sum, line) => sum + line.quantity, 0);
}

export function portionLabel(count: number) {
  const form = plurals.select(count);
  return count + " " + (form === "one" ? "порция" : form === "few" ? "порции" : "порций");
}
