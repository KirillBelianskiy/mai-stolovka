import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CancelDialog } from "../../kitchen-app/src/components/cancel-dialog";

const originalShowModal = Object.getOwnPropertyDescriptor(
  HTMLDialogElement.prototype,
  "showModal",
);
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
});
afterEach(() => {
  cleanup();
  if (originalShowModal)
    Object.defineProperty(
      HTMLDialogElement.prototype,
      "showModal",
      originalShowModal,
    );
  else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
});

test("staff cancellation requires an explicit confirmation", () => {
  const onConfirm = vi.fn(),
    onDismiss = vi.fn();
  render(
    <CancelDialog
      number="MAI-1045"
      busy={false}
      onConfirm={onConfirm}
      onDismiss={onDismiss}
    />,
  );
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить заказ" }));
  expect(onDismiss).toHaveBeenCalledOnce();
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Да, отменить заказ" }));
  expect(onConfirm).toHaveBeenCalledOnce();
});

test("busy confirmation cannot submit or dismiss", () => {
  const onConfirm = vi.fn(),
    onDismiss = vi.fn();
  render(
    <CancelDialog
      number="MAI-1045"
      busy
      onConfirm={onConfirm}
      onDismiss={onDismiss}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Да, отменить заказ" }));
  fireEvent.click(screen.getByRole("button", { name: "Сохранить заказ" }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(onDismiss).not.toHaveBeenCalled();
});
