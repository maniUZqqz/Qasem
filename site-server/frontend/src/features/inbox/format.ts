import { CHANNEL_COLOR } from "./api";

const FA = "۰۱۲۳۴۵۶۷۸۹";
export const faNum = (n: number | string) => String(n).replace(/\d/g, (d) => FA[Number(d)]);

/** «۵ دقیقه»، «۲ ساعت و ۱۰ دقیقه» — برای مدت‌ها. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${faNum(s)} ثانیه`;
  const m = Math.round(s / 60);
  if (m < 60) return `${faNum(m)} دقیقه`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h < 48) return rest ? `${faNum(h)} ساعت و ${faNum(rest)} دقیقه` : `${faNum(h)} ساعت`;
  return `${faNum(Math.round(h / 24))} روز`;
}

export function minutesText(minutes: number | null | undefined): string {
  return minutes === null || minutes === undefined ? "" : duration(minutes * 60);
}

/** «۳ دقیقه پیش» برای یک لحظه؛ برای قدیمی‌ها تاریخ شمسی. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "همین الان";
  if (diff < 3600) return `${faNum(Math.round(diff / 60))} دقیقه پیش`;
  if (diff < 86400) return `${faNum(Math.round(diff / 3600))} ساعت پیش`;
  if (diff < 86400 * 7) return `${faNum(Math.round(diff / 86400))} روز پیش`;
  return dateText(iso);
}

export function dateText(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fa-IR", { year: "numeric", month: "short", day: "numeric" });
}

export function dateTimeText(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
}

export const channelColor = (key: string) => CHANNEL_COLOR[key] ?? "#8a94a8";

export function money(value: number): string {
  return `${Math.round(value).toLocaleString("fa-IR")} ریال`;
}

export function initials(name: string): string {
  const clean = (name || "").trim();
  if (!clean) return "؟";
  const parts = clean.split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** تبدیل متنِ آزادِ کاربر به عددِ امن برای ورودی‌های عددی (فارسی هم می‌پذیرد). */
export function toInt(text: string, fallback = 0): number {
  const ascii = text.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d)));
  const n = parseInt(ascii, 10);
  return Number.isFinite(n) ? n : fallback;
}

export function copy(text: string): Promise<void> {
  try {
    return navigator.clipboard.writeText(text);
  } catch {
    return Promise.reject(new Error("کلیپ‌بورد در دسترس نیست"));
  }
}

/** «۲۰۲۶-۱۱-۲۰T۰۹:۰۰» برای ورودی datetime-local: ساعتِ دیواریِ مرورگر، نه UTC (وگرنه ویرایش، زمان را جابه‌جا می‌کند). */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const NO_NAME = new Set(["", "مشتری", "بازدیدکنندهٔ سایت", "بازدیدکننده", "مشتری آزمایشی"]);

/** `{name}` / `{نام}` را با نامِ کوچکِ مشتری پر می‌کند (همان قاعدهٔ سرور؛ نامِ ناشناخته = «دوست عزیز»). */
export function fillName(text: string, name: string | null | undefined): string {
  const clean = (name ?? "").trim();
  const usable = clean && !NO_NAME.has(clean) && /\p{L}/u.test(clean) ? clean.split(/\s+/)[0] : "";
  return text.replace(/\{\s*(?:name|نام)\s*\}/gi, usable || "دوست عزیز");
}
