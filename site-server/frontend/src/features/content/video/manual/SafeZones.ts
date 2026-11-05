/**
 * ناحیه‌های امنِ شبکه‌های اجتماعی: حاشیه‌هایی از قاب (کسری) که رابطِ برنامه (نام، دکمه‌ها، توضیح) رویشان می‌افتد؛
 * زیرنویس و لوگو باید از آن‌ها دور بمانند. سرور همین فهرست را در `catalogue.safe_zones` می‌دهد؛ این ثابت فقط جایگزینِ ایمن است.
 */
export type SafeMargins = { top: number; bottom: number; left: number; right: number };
export type SafeZone = { key: string; title: string; hint: string; margins: SafeMargins };

/** تنها جایگزینِ داخلیِ فهرست (وقتی کاتالوگِ سرور هنوز نیامده یا safe_zones ندارد) */
export const SAFE_ZONES_FALLBACK: SafeZone[] = [
  { key: "reels", title: "ریلز اینستاگرام", hint: "بالا: نام و دوربین؛ پایین: توضیح و موسیقی؛ راست: دکمه‌ها", margins: { top: 0.13, bottom: 0.22, left: 0.05, right: 0.14 } },
  { key: "story", title: "استوری", hint: "بالا: نامِ صفحه؛ پایین: پاسخ‌دادن", margins: { top: 0.13, bottom: 0.13, left: 0.05, right: 0.05 } },
  { key: "tiktok", title: "تیک‌تاک", hint: "بالا: جست‌وجو؛ پایین: توضیح؛ راست: دکمه‌ها", margins: { top: 0.11, bottom: 0.24, left: 0.05, right: 0.17 } },
  { key: "shorts", title: "شورتس یوتیوب", hint: "پایین: عنوان و کانال؛ راست: دکمه‌ها", margins: { top: 0.10, bottom: 0.20, left: 0.05, right: 0.14 } },
  { key: "feed", title: "پست", hint: "حاشیهٔ کوچکِ دورِ پست", margins: { top: 0.05, bottom: 0.05, left: 0.05, right: 0.05 } },
];

export const SAFE_OFF = "off";
/** همان دو کادرِ خط‌چینِ قدیمی (۵٪ و ۱۰٪) */
export const SAFE_GENERAL = "general";
export const SAFE_STORAGE_KEY = "nm.video.safezone";

/** فهرستِ ناحیه‌ها: از کاتالوگِ سرور اگر بود، وگرنه جایگزین */
export function safeZonesOf(fromCatalogue?: SafeZone[] | null): SafeZone[] {
  return fromCatalogue && fromCatalogue.length ? fromCatalogue : SAFE_ZONES_FALLBACK;
}

/** کلیدِ ذخیره‌شده (خاموش اگر نبود یا حافظه در دسترس نبود) */
export function readSafeZone(): string {
  try {
    return window.localStorage.getItem(SAFE_STORAGE_KEY) || SAFE_OFF;
  } catch {
    return SAFE_OFF;
  }
}

export function writeSafeZone(key: string): void {
  try {
    window.localStorage.setItem(SAFE_STORAGE_KEY, key);
  } catch {
    /* حافظه بسته است؛ فقط برای همین نشست می‌ماند */
  }
}

/** ناحیه‌ای که کلیدش `key` است؛ برای «خاموش/عمومی» یا کلیدِ ناشناخته undefined */
export function zoneByKey(zones: SafeZone[], key: string): SafeZone | undefined {
  return zones.find((z) => z.key === key);
}

/**
 * آیا مرکزِ یک زیرنویس/لوگو در ارتفاعِ `y` (کسری از قاب، ۰ = بالا) داخلِ ناحیهٔ امنِ عمودیِ `zone` است؟
 * بدونِ ناحیه همیشه true. (فعلاً رابط از آن استفاده نمی‌کند؛ برای هشدارها و آزمون‌ها.)
 */
export function captionInsideSafe(zone: SafeZone | null | undefined, y: number): boolean {
  if (!zone) return true;
  return y >= zone.margins.top && y <= 1 - zone.margins.bottom;
}
