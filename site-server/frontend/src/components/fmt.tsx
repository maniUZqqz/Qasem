import { ReactNode } from "react";

/**
 * Small formatting helpers shared by pages that show server text to a person.
 *
 * - `faDateTime`: ONE way to write a moment. The panel used to print
 *   «۲۰۲۶-۱۱-۱۴ ۰۲:۳۰» (UTC, Gregorian) and «۱۴۰۵/۸/۲۳، ۳:۳۰:۱۰» (local, Shamsi
 *   without padding) on the same card.
 * - `RichText`: the few inline marks the backend notes use («**مهم**»,
 *   «`mode=enhance`») rendered instead of printed.
 * - `UNLIMITED_STOCK`: a service with no stock is stored as 9999 (see
 *   apps/products/digital.py); it is shown as a service, never as «۹۹۹۹ عدد».
 */

/** Same sentinel as `apps.products.digital.UNLIMITED_STOCK`. */
export const UNLIMITED_STOCK = 9999;

export function isUnlimitedStock(quantity: number | null | undefined): boolean {
  return (quantity ?? 0) >= UNLIMITED_STOCK;
}

const PARTS = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Tehran",
});

/** «۱۴۰۵/۰۸/۲۳ ۰۶:۰۰» in Tehran time; "" for anything unreadable. */
export function faDateTime(value: string | number | Date | null | undefined, withTime = true): string {
  if (value === null || value === undefined || value === "") return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const got: Record<string, string> = {};
  for (const part of PARTS.formatToParts(date)) got[part.type] = part.value;
  const day = `${got.year}/${got.month}/${got.day}`;
  return withTime ? `${day} ${got.hour}:${got.minute}` : day;
}

/** Renders «**bold**» and «`code`»; everything else is plain text (never HTML). */
export function RichText({ text }: { text: string }): ReactNode {
  const parts = String(text ?? "")
    .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    .filter((p) => p !== "");
  return (
    <>
      {parts.map((part, i) => {
        if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
          return (
            <code
              key={i}
              dir="ltr"
              className="rounded px-1 text-[0.9em]"
              style={{ background: "var(--surface-2)", color: "var(--text)" }}
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
