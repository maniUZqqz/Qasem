import type { Idea } from "./api";

/** منطقِ خالصِ بانکِ ایده (بدونِ شبکه) — آزمون: tests/ideas-bank.test.ts */

/** «۱۲۳» ⇒ ارقامِ فارسی. */
export function faDigits(n: number | string): string {
  return String(n).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

/** جست‌وجوی هم‌شکل: ی/ک عربی، نیم‌فاصله، اعراب و ارقام (همان قاعدهٔ سرور). */
export function fold(text: string): string {
  return String(text || "")
    .replace(/[ً-ٰٟ]/g, "")
    .replace(/ي|ى/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/‌/g, " ")
    .replace(/ـ/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase()
    .trim();
}

export function matches(i: Idea, q: string): boolean {
  const words = fold(q).split(" ").filter(Boolean);
  if (!words.length) return true;
  const hay = fold(
    [i.title, i.logline, i.hook, i.shoot, i.cta, i.filled.title, i.filled.logline, i.filled.hook, i.filled.shoot, i.filled.cta, ...i.tags, i.occasion?.name ?? "", i.key.replace(/_/g, " ")].join(" "),
  );
  return words.every((w) => hay.includes(w));
}

/** «2026-12-21» ⇒ «۳۰ آذر ۱۴۰۵» (تقویمِ شمسیِ مرورگر؛ اگر نبود خالی). */
export function jalaliText(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return "";
  try {
    return new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "long", year: "numeric" }).format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12)));
  } catch {
    return "";
  }
}
