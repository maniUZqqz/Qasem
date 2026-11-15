/**
 * جست‌وجوی سبک‌ها در مرورگر؛ همان قاعدهٔ سرور (backend/apps/looks/library.py: fold / matches).
 * SOURCE: ported from InstAI:frontend/src/library.ts @ 2f8aa90, adapted for store advertising (NMarketing).
 *
 * حروفِ عربی/فارسی، نیم‌فاصله، ارقام و علائم نگارشی فرقی نمی‌کند؛ هر واژه باید در نام، توضیح، برچسب، نام‌های جست‌وجو (alias) یا کلید بیاید.
 * آزمونِ سرور (tests_library) می‌سنجد فهرستِ علائمِ نادیده‌گرفته‌شده با سرور یکی باشد.
 */
import type { LookEntry } from "./api";

const PUNCTUATION = /[()\[\]{}<>«»"“”‘’,;:!?،؛؟/\\|]/g;
/** واژه‌های بی‌اثر در جست‌وجو («PS2 style»، «Lego-like bricks»): جزوِ نامِ سبک نیستند */
const FILLER = new Set(["style", "styles", "look", "looks", "like", "سبک", "استایل"]);
const DIGITS: Record<string, string> = {
  "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
  "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
};

export function fold(text: string): string {
  return (text || "")
    .replace(PUNCTUATION, " ")
    .toLowerCase()
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/‌/g, " ")
    .replace(/-/g, " ")
    .replace(/[٠-٩۰-۹]/g, (d) => DIGITS[d] ?? d);
}

export function lookMatches(row: LookEntry, q: string): boolean {
  let words = fold(q).split(/\s+/).filter(Boolean);
  const kept = words.filter((w) => !FILLER.has(w));
  words = kept.length ? kept : words;
  if (!words.length) return true;
  const hay = fold(
    [row.name_fa, row.name_en, row.description_fa, (row.tags || []).join(" "), (row.search_terms || []).join(" "), row.key.replace(/_/g, " "), row.known_as || ""].join(" "),
  );
  return words.every((w) => hay.includes(w));
}
