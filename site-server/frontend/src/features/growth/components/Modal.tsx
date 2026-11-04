import { ReactNode, useEffect, useRef } from "react";

import Icon from "../../../components/Icon";
import { Button } from "../../../components/ui";

/**
 * A dialog: centred card over a dim backdrop. Escape and the backdrop close it, the page behind does not
 * scroll, focus moves inside and returns afterwards. Works RTL (it uses logical properties only).
 */
export default function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  size = "md",
  busy = false,
  testId,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** while true the dialog cannot be dismissed (a request is in flight) */
  busy?: boolean;
  testId?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    const focusable = panel.current?.querySelector<HTMLElement>("[data-autofocus], input, select, textarea, button:not([data-modal-close])");
    (focusable ?? panel.current)?.focus();
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [open, busy, onClose]);

  if (!open) return null;
  const width = { sm: "28rem", md: "36rem", lg: "52rem", xl: "72rem" }[size];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={title} data-testid={testId}>
      <div className="absolute inset-0" style={{ background: "rgb(2 4 10 / .72)" }} onClick={() => !busy && onClose()} />
      <div
        ref={panel}
        tabIndex={-1}
        className="u-card u-rise relative flex max-h-[92dvh] w-full flex-col outline-none"
        style={{ maxWidth: width, background: "var(--void-2)", borderColor: "var(--line-strong)" }}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4" style={{ borderBottom: "1px solid var(--line)" }}>
          <h2 className="text-base font-extrabold" style={{ color: "var(--text)" }}>
            {title}
          </h2>
          <button type="button" className="u-btn u-btn-ghost u-btn-sm" data-modal-close onClick={() => !busy && onClose()} aria-label="بستن" disabled={busy}>
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-3" style={{ borderTop: "1px solid var(--line)" }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/** «مطمئنید؟» - a small confirmation dialog for destructive actions. */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "تأیید",
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      size="sm"
      busy={busy}
      testId="confirm-dialog"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            انصراف
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy} data-autofocus data-testid="confirm-yes">
            {busy ? "در حال انجام…" : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
        {message}
      </div>
    </Modal>
  );
}
