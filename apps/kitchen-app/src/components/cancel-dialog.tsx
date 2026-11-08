"use client";

import { useEffect, useId, useRef } from "react";

export function CancelDialog({
  number,
  busy,
  onDismiss,
  onConfirm,
}: {
  number: string;
  busy: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      className="cancel-dialog"
      aria-labelledby={title}
      onClose={onDismiss}
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
    >
      <h2 id={title}>Отменить {number}?</h2>
      <p>
        Отмена будет подтверждена сервером. После операции проверьте обновлённый
        статус заказа.
      </p>
      <div>
        <button
          className="secondary-button"
          autoFocus
          disabled={busy}
          onClick={onDismiss}
        >
          Сохранить заказ
        </button>
        <button className="primary-button" disabled={busy} onClick={onConfirm}>
          Да, отменить заказ
        </button>
      </div>
    </dialog>
  );
}
