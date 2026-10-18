import { ReactNode } from "react";

import Icon, { type IconName } from "./Icon";

/**
 * Panel primitives.
 *
 * Everything styles itself from the CSS tokens in index.css, so dark mode is
 * a single attribute on <html> rather than a variant on every class. The
 * older components (Button, Input, Card…) keep their original props, so the
 * feature pages built against them needed no rewrite.
 */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  children,
  variant = "primary",
  size,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm";
}) {
  return (
    <button
      {...props}
      className={[
        "u-btn",
        `u-btn-${variant}`,
        size === "sm" ? "u-btn-sm" : "",
        props.className ?? "",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`u-input ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`u-input ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`u-input ${props.className ?? ""}`} />;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span
        className="mb-1.5 block text-sm font-medium"
        style={{ color: "var(--text-2)" }}
      >
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </span>
      )}
    </label>
  );
}

export function Card({
  children,
  className = "",
  padded = true,
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  /** Adds lift + glow on hover. Only for cards that are actually clickable —
   *  a card that reacts to the pointer but does nothing is a broken promise. */
  hover?: boolean;
}) {
  return (
    <div className={`u-card ${hover ? "u-card-hover" : ""} ${padded ? "p-5" : ""} ${className}`}>
      {children}
    </div>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
        {children}
      </h2>
      {action}
    </div>
  );
}

/** Page header: title, optional subtitle, optional right-hand actions. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold" style={{ color: "var(--text)" }}>
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm" style={{ color: "var(--text-3)" }}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return <span className={`u-badge u-badge-${tone}`}>{children}</span>;
}

/** A single number with its label — the dashboard's building block. */
export function Stat({
  value,
  label,
  hint,
  tone,
}: {
  value: ReactNode;
  label: string;
  hint?: string;
  tone?: Tone;
}) {
  const color =
    tone && tone !== "neutral" ? `var(--${tone === "brand" ? "brand" : tone})` : "var(--text)";
  return (
    <Card>
      <div className="u-num text-2xl font-extrabold" style={{ color }}>
        {value}
      </div>
      <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
        {label}
      </div>
      {hint && (
        <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </div>
      )}
    </Card>
  );
}

/** Usage bar. Turns amber past 70% and red past 90% so a customer sees the
 *  ceiling coming instead of hitting it mid-campaign. */
export function Meter({ used, total }: { used: number; total: number }) {
  const percent = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const color =
    percent >= 90 ? "var(--bad)" : percent >= 70 ? "var(--warn)" : "var(--ok)";
  return (
    <div className="u-meter">
      <span style={{ width: `${percent}%`, background: color }} />
    </div>
  );
}

export function Spinner({ size = 22 }: { size?: number }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        display: "inline-block",
        border: "2px solid var(--line-strong)",
        borderTopColor: "var(--brand)",
        borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
      }}
      role="status"
      aria-label="در حال بارگذاری"
    >
      <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
    </span>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`u-skeleton ${className}`} />;
}

/** Shown instead of an empty list — an empty screen with no explanation is
 *  the most common reason a new user thinks the product is broken. */
export function EmptyState({
  icon = "empty",
  title,
  description,
  action,
  children,
}: {
  icon?: IconName;
  /** Optional so the older call sites that pass only children keep working. */
  title?: string;
  description?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span
        className="mb-1 grid h-12 w-12 place-items-center rounded-2xl"
        style={{
          background: "var(--surface-2)",
          border: "1px solid var(--line)",
          color: "var(--text-3)",
        }}
      >
        <Icon name={icon} size={22} />
      </span>
      {title && (
        <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
          {title}
        </h3>
      )}
      {children && (
        <p className="max-w-sm text-sm" style={{ color: "var(--text-3)" }}>
          {children}
        </p>
      )}
      {description && (
        <p className="max-w-sm text-sm" style={{ color: "var(--text-3)" }}>
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Inline message. `tone` carries the meaning; the icon only reinforces it. */
export function Alert({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const icon: IconName = (
    { ok: "ok", warn: "warn", bad: "ban", info: "info", brand: "bulb", neutral: "info" } as const
  )[tone];
  return (
    <div
      className="flex items-start gap-3 rounded-xl p-4"
      style={{
        background: `var(--${tone === "neutral" ? "surface-2" : tone}-soft, var(--surface-2))`,
        border: `1px solid color-mix(in srgb, var(--${tone === "neutral" ? "line" : tone}) 30%, transparent)`,
      }}
    >
      <span className="mt-0.5 shrink-0" style={{ color: `var(--${tone === "neutral" ? "text-3" : tone})` }}>
        <Icon name={icon} size={17} />
      </span>
      <div className="min-w-0 flex-1">
        {title && (
          <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
            {title}
          </div>
        )}
        {children && (
          <div className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {children}
          </div>
        )}
      </div>
      {action}
    </div>
  );
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="u-table">{children}</table>
    </div>
  );
}

/** ۱۲۳۴ → «۱٬۲۳۴» */
export function fa(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

export function toman(value: number): string {
  return fa(value.toLocaleString("en-US")).replace(/,/g, "٬");
}

/* ------------------------------------------------------------------------
   Kept from the first version of the panel so the feature pages built
   against them keep working. They now read the same tokens as everything
   else, so they follow the theme.
   ------------------------------------------------------------------------ */

/** Small inline tag. `Badge` is the richer, tone-aware version. */
export function Chip({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-block rounded-full px-2.5 py-1 text-xs"
      style={{ background: "var(--surface-2)", color: "var(--text-2)" }}
    >
      {children}
    </span>
  );
}

/** Error banner. Renders nothing when there is no message, so call sites can
 *  drop it in unconditionally. */
export function ErrorBox({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div
      className="rounded-xl px-4 py-3 text-sm"
      style={{
        background: "var(--bad-soft)",
        color: "var(--bad)",
        border: "1px solid color-mix(in srgb, var(--bad) 30%, transparent)",
      }}
    >
      {message}
    </div>
  );
}
