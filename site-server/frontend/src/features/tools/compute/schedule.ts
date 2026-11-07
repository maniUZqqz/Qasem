/**
 * منطقِ خالصِ «زمان‌بندیِ دانلود» (بدونِ React و DOM، تا بدونِ مرورگر آزمون شود): کارتِ تنظیمِ کلی، انتخابگرِ زمانِ هر دانلود
 * (`DownloadWhen`) و برچسبِ «زمان‌بندی‌شده — شروع امروز ۰۲:۰۰».
 *
 * همهٔ ساعت‌ها به وقتِ تهران‌اند (UTC+3:30، بدونِ ساعتِ تابستانی)؛ مرورگر هر منطقه‌ای داشته باشد فرقی نمی‌کند، چون با
 * جابه‌جاییِ ثابتِ ۳:۳۰ حساب می‌کنیم — همان قاعدهٔ apps/compute/schedule.py در سایت و عاملِ سرورِ پردازش.
 * آزمون: frontend/tests/compute-schedule.test.ts
 */
import { toFa } from "./queue/model";

export type WhenMode = "default" | "now" | "at" | "window";
/** انتخابِ کاربر برای یک دانلود؛ `time` فقط وقتی mode = "at" است («HH:MM») */
export type WhenChoice = { mode: WhenMode; time: string };
export type DownloadMode = "now" | "window";
/** تنظیمِ کلیِ دانلودها (همان POST /compute/settings/): همین الان یا فقط در بازهٔ شبانه */
export type DownloadSettings = { mode: DownloadMode; start: string; end: string };

export const TEHRAN_OFFSET_MS = (3 * 60 + 30) * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
export const DEFAULT_WINDOW = { start: "02:00", end: "07:00" } as const;
export const DEFAULT_AT = "03:00";
export const DEFAULT_WHEN: WhenChoice = { mode: "default", time: DEFAULT_AT };
export const DEFAULT_SETTINGS: DownloadSettings = { mode: "now", start: DEFAULT_WINDOW.start, end: DEFAULT_WINDOW.end };

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

function asciiDigits(text: string): string {
  return text.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d))).replace(/[٠-٩]/g, (d) => String(AR_DIGITS.indexOf(d)));
}

const pad = (n: number) => String(n).padStart(2, "0");

// ───────────────────────────── ساعت و بازه

/** «۳:۳۰» / «۰۳:۳۰» / «03:30» ⇒ «03:30»؛ نامعتبر ⇒ null */
export function normalizeClock(text: string | null | undefined): string | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(asciiDigits(String(text ?? "")).trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${pad(h)}:${pad(min)}`;
}

const minuteOf = (hhmm: string): number => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** «02:00-07:00» ⇒ {start, end}؛ خالی، نامعتبر یا شروع = پایان ⇒ null (مثلِ parse_window ِ سایت) */
export function parseWindow(text: string | null | undefined): { start: string; end: string } | null {
  const parts = asciiDigits(String(text ?? "")).split("-");
  if (parts.length !== 2) return null;
  const start = normalizeClock(parts[0]);
  const end = normalizeClock(parts[1]);
  if (!start || !end || start === end) return null;
  return { start, end };
}

export function joinWindow(start: string, end: string): string | null {
  const s = normalizeClock(start);
  const e = normalizeClock(end);
  if (!s || !e || s === e) return null;
  return `${s}-${e}`;
}

/** «۰۲:۰۰» برای نمایش */
export function clockFa(hhmm: string): string {
  return toFa(hhmm);
}

/** «۰۲:۰۰ تا ۰۷:۰۰» */
export function windowFa(window: string | null | undefined): string {
  const w = parseWindow(window);
  return w ? `${clockFa(w.start)} تا ${clockFa(w.end)}` : "";
}

// ───────────────────────────── حسابِ زمان به وقتِ تهران

/** دقیقه از نیمه‌شبِ تهران */
function tehranMinute(nowMs: number): number {
  const t = nowMs + TEHRAN_OFFSET_MS;
  return Math.floor((((t % DAY_MS) + DAY_MS) % DAY_MS) / 60000);
}

/** الان (یا nowMs) داخلِ بازه است؟ بازهٔ خالی/نامعتبر ⇒ همیشه بله؛ بازهٔ نیمه‌شب (۲۲:۰۰-۰۴:۰۰) هم درست است */
export function inWindow(window: string | null | undefined, nowMs: number = Date.now()): boolean {
  const w = parseWindow(window);
  if (!w) return true;
  const s = minuteOf(w.start);
  const e = minuteOf(w.end);
  const m = tehranMinute(nowMs);
  return s < e ? m >= s && m < e : m >= s || m < e;
}

/** نخستین لحظهٔ (ms) که ساعتِ دیواریِ تهران hh:mm است و از nowMs گذشته نیست؛ نامعتبر ⇒ null */
export function nextClockMs(hhmm: string, nowMs: number = Date.now()): number | null {
  const c = normalizeClock(hhmm);
  if (!c) return null;
  const t = nowMs + TEHRAN_OFFSET_MS;
  const dayStart = Math.floor(t / DAY_MS) * DAY_MS;
  let target = dayStart + minuteOf(c) * 60000;
  if (target <= t) target += DAY_MS;
  return target - TEHRAN_OFFSET_MS;
}

/** نخستین لحظه‌ای که بازه باز می‌شود؛ اگر الان بازه باز است همان nowMs؛ بازهٔ نامعتبر ⇒ nowMs */
export function nextWindowStartMs(window: string | null | undefined, nowMs: number = Date.now()): number {
  const w = parseWindow(window);
  if (!w || inWindow(window, nowMs)) return nowMs;
  return nextClockMs(w.start, nowMs) ?? nowMs;
}

/** «امروز ۰۲:۰۰» / «فردا ۰۲:۰۰» / «۳ روزِ دیگر، ۰۲:۰۰» (به وقتِ تهران) */
export function clockLabel(ms: number, nowMs: number = Date.now()): string {
  const t = ms + TEHRAN_OFFSET_MS;
  const day = Math.floor(t / DAY_MS) - Math.floor((nowMs + TEHRAN_OFFSET_MS) / DAY_MS);
  const hhmm = toFa(`${pad(Math.floor((((t % DAY_MS) + DAY_MS) % DAY_MS) / 3600000))}:${pad(Math.floor((((t % 3600000) + 3600000) % 3600000) / 60000))}`);
  if (day <= 0) return `امروز ${hhmm}`;
  if (day === 1) return `فردا ${hhmm}`;
  return `${toFa(day)} روزِ دیگر، ${hhmm}`;
}

/**
 * کی کارِ زمان‌بندی‌شده می‌تواند شروع شود؟ null = همین حالا. اگر هم زمان (scheduled_for) هم بازه هست، دیرتر از این دو
 * (مثلِ start_moment ِ سایت).
 */
export function startMoment(
  job: { scheduled_for?: string | null; window?: string | null },
  nowMs: number = Date.now(),
): number | null {
  const parsed = job.scheduled_for ? Date.parse(job.scheduled_for) : NaN;
  let moment = Number.isFinite(parsed) && parsed > nowMs ? parsed : null;
  if (job.window && !inWindow(job.window, nowMs)) {
    const opens = nextWindowStartMs(job.window, nowMs);
    moment = moment === null ? opens : Math.max(moment, opens);
  }
  return moment;
}

/** «زمان‌بندی‌شده — شروع امروز ۰۲:۰۰» (با withZone: «… (به وقتِ تهران)»)؛ کاری که همین حالا می‌تواند شروع شود ⇒ «» */
export function scheduleLabel(
  job: { scheduled_for?: string | null; window?: string | null },
  nowMs: number = Date.now(),
  withZone = false,
): string {
  const moment = startMoment(job, nowMs);
  if (moment === null) return "";
  return `زمان‌بندی‌شده — شروع ${clockLabel(moment, nowMs)}${withZone ? " (به وقتِ تهران)" : ""}`;
}

// ───────────────────────────── کارتِ تنظیمِ کلی

/** پاسخِ GET /compute/settings/ ⇒ تنظیماتِ کارت (نبودنِ فیلد = پیش‌فرض: همین الان، ۰۲:۰۰ تا ۰۷:۰۰) */
export function settingsFromServer(raw: unknown): DownloadSettings {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const w = parseWindow(typeof r.download_window === "string" ? r.download_window : "");
  return {
    mode: r.download_mode === "window" ? "window" : "now",
    start: w?.start ?? DEFAULT_WINDOW.start,
    end: w?.end ?? DEFAULT_WINDOW.end,
  };
}

/** خطای فارسیِ فرم؛ «» یعنی درست است */
export function settingsError(s: DownloadSettings): string {
  if (s.mode !== "window") return "";
  if (!normalizeClock(s.start) || !normalizeClock(s.end)) return "ساعتِ شروع و پایان را کامل بنویسید.";
  if (normalizeClock(s.start) === normalizeClock(s.end)) return "ساعتِ شروع و پایان نباید یکی باشند.";
  return "";
}

/** بدنهٔ POST /compute/settings/ (بازه همیشه فرستاده می‌شود تا با «همین الان» هم ذخیره بماند)؛ فرمِ نادرست ⇒ null */
export function settingsBody(s: DownloadSettings): { download_mode: DownloadMode; download_window: string } | null {
  if (settingsError(s)) return null;
  const joined = joinWindow(s.start, s.end) ?? joinWindow(DEFAULT_WINDOW.start, DEFAULT_WINDOW.end)!;
  return { download_mode: s.mode, download_window: joined };
}

export function sameSettings(a: DownloadSettings, b: DownloadSettings): boolean {
  return a.mode === b.mode && (a.mode === "now" || (normalizeClock(a.start) === normalizeClock(b.start) && normalizeClock(a.end) === normalizeClock(b.end)));
}

/** یک جملهٔ ساده که می‌گوید با این تنظیم چه می‌شود */
export function describeSettings(s: DownloadSettings): string {
  if (s.mode !== "window") return "دانلودها همین که درخواست شوند شروع می‌شوند.";
  return (
    `دانلودها فقط شب‌ها، از ساعتِ ${clockFa(normalizeClock(s.start) ?? s.start)} تا ${clockFa(normalizeClock(s.end) ?? s.end)} ` +
    "(به وقتِ تهران) انجام می‌شوند. دانلودی که بیرون از این ساعت‌ها بخواهید در صف می‌ماند و در اولین بازه خودش شروع می‌شود؛ " +
    "اگر وسطِ دانلود بازه تمام شود، می‌ایستد و بازهٔ بعدی از همان‌جا ادامه می‌دهد."
  );
}

/** جملهٔ ثابتِ «چه چیزی فوری است» که زیرِ کارت نوشته می‌شود */
export const IMMEDIATE_NOTE =
  "به‌روزرسانیِ خودِ سرورِ پردازش و دانلودهایی که همین الان لازمِ یک کارِ در حال اجرا هستند فوری‌اند و منتظرِ بازه نمی‌مانند.";

// ───────────────────────────── انتخابگرِ زمانِ یک دانلود

export const WHEN_OPTIONS: { mode: WhenMode; label: string }[] = [
  { mode: "default", label: "طبقِ تنظیمِ کلی" },
  { mode: "now", label: "الان" },
  { mode: "at", label: "در ساعتِ" },
  { mode: "window", label: "در بازهٔ شبانه (طبقِ تنظیمات)" },
];

export function whenValid(c: WhenChoice): boolean {
  return c.mode !== "at" || normalizeClock(c.time) !== null;
}

export function whenError(c: WhenChoice): string {
  return whenValid(c) ? "" : "ساعت را مثل ۰۳:۳۰ بنویسید.";
}

/** بدنهٔ `when` در POST؛ «طبقِ تنظیمِ کلی» ⇒ undefined (فرستاده نمی‌شود) */
export function whenBody(c: WhenChoice): { mode: WhenMode; time?: string } | undefined {
  if (c.mode === "default") return undefined;
  if (c.mode === "at") return { mode: "at", time: normalizeClock(c.time) ?? c.time };
  return { mode: c.mode };
}

/** جملهٔ کوتاهِ «چه موقع شروع می‌شود» برای زیرِ انتخابگر و پیامِ تأیید */
export function whenSummary(c: WhenChoice, settings: DownloadSettings | null, nowMs: number = Date.now()): string {
  if (c.mode === "now") return "همین الان شروع می‌شود.";
  if (c.mode === "at") {
    const moment = nextClockMs(c.time, nowMs);
    const clock = normalizeClock(c.time);
    if (moment === null || !clock) return "ساعت را مثل ۰۳:۳۰ بنویسید.";
    return `در ساعتِ ${clockFa(clock)} (به وقتِ تهران) شروع می‌شود — ${clockLabel(moment, nowMs)}.`;
  }
  const useWindow = c.mode === "window" || (c.mode === "default" && settings?.mode === "window");
  if (!useWindow) return c.mode === "default" ? "طبقِ تنظیمِ کلی: همین الان شروع می‌شود." : "همین الان شروع می‌شود.";
  const s = settings ?? DEFAULT_SETTINGS;
  const win = joinWindow(s.start, s.end) ?? `${DEFAULT_WINDOW.start}-${DEFAULT_WINDOW.end}`;
  const prefix = c.mode === "default" ? "طبقِ تنظیمِ کلی: " : "";
  if (inWindow(win, nowMs)) return `${prefix}الان در بازهٔ شبانه (${windowFa(win)}) هستیم؛ همین حالا شروع می‌شود.`;
  return `${prefix}در بازهٔ شبانه (${windowFa(win)}، به وقتِ تهران) شروع می‌شود — ${clockLabel(nextWindowStartMs(win, nowMs), nowMs)}.`;
}

/** متنِ پرسشِ تأیید (دانلودِ مدل) با زمانِ انتخاب‌شده */
export function whenConfirmLine(c: WhenChoice, settings: DownloadSettings | null, nowMs: number = Date.now()): string {
  return `زمانِ شروع: ${whenSummary(c, settings, nowMs)}`;
}
