/**
 * منطقِ خالصِ «تدوینِ خودکار» — بدونِ React، تا با esbuild/node آزموده شود.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/autoedit-logic.test.ts --bundle --platform=node --format=esm --outfile=/tmp/autoedit-logic.test.mjs
 *   node /tmp/autoedit-logic.test.mjs
 */

export type SilenceAction = "keep" | "shorten" | "cut";

export type SilenceRow = {
  id: string;
  start: number;
  end: number;
  len: number;
  kind: string;
  suggest: SilenceAction;
  reason: string;
  before: string;
  after: string;
  action?: SilenceAction;
  answered?: boolean;
};

export const ACTION_LABEL: Record<SilenceAction, string> = {
  keep: "نگه‌دار",
  shorten: "کوتاهش کن",
  cut: "ببُر",
};

export const ACTION_HINT: Record<SilenceAction, string> = {
  keep: "مکثِ عمدی است؛ همان‌طور بماند",
  shorten: "کمی کوتاه شود ولی هنوز مکث حس شود",
  cut: "کاملاً برداشته شود",
};

/** ثانیه ← «۱:۰۵٫۴» (ارقام لاتین؛ نمایشگر با fa() فارسی می‌کند) */
export function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return `${m}:${rest < 10 ? "0" : ""}${rest.toFixed(1)}`;
}

/** پاسخِ آغازینِ هر پرسش: پیشنهادِ خودِ سیستم (یک لمس کافی است) */
export function seedChoices(questions: SilenceRow[], existing: Record<string, SilenceAction> = {}): Record<string, SilenceAction> {
  const out: Record<string, SilenceAction> = {};
  for (const q of questions) out[q.id] = existing[q.id] ?? q.suggest;
  return out;
}

/** ردیف‌های API ← بدنهٔ ذخیره (فقط پرسش‌هایی که انتخاب دارند) */
export function toAnswers(questions: SilenceRow[], choices: Record<string, SilenceAction>): { start: number; end: number; action: SilenceAction }[] {
  return questions.filter((q) => choices[q.id]).map((q) => ({ start: q.start, end: q.end, action: choices[q.id] }));
}

/** پنجرهٔ شنیدن: کمی پیش از مکث تا کمی بعد از آن، تا کاربر بشنود مکث «در جایش» چطور است */
export function previewWindow(q: { start: number; end: number }, duration: number, pad = 1.6): { from: number; to: number } {
  const from = Math.max(0, q.start - pad);
  const to = Math.min(duration > 0 ? duration : q.end + pad, q.end + pad);
  return { from, to: Math.max(from + 0.5, to) };
}

/** چند پرسش هنوز بی‌پاسخ است */
export function openCount(questions: SilenceRow[]): number {
  return questions.filter((q) => !q.answered).length;
}

/** جمع‌بندیِ یک خطی از شمارش‌ها */
export function countsLine(counts: Partial<Record<SilenceAction, number>>, removedSeconds: number, f: (n: number | string) => string): string {
  const parts: string[] = [];
  if (counts.cut) parts.push(`${f(counts.cut)} مکثِ بی‌دلیل بریده`);
  if (counts.shorten) parts.push(`${f(counts.shorten)} مکث کوتاه`);
  if (counts.keep) parts.push(`${f(counts.keep)} مکث دست‌نخورده`);
  const tail = removedSeconds > 0 ? ` — جمعاً ${f(Math.round(removedSeconds * 10) / 10)} ثانیه کم می‌شود` : "";
  return parts.join("، ") + tail;
}

/** صدا فقط از یکی از دو ویدیوی «قبل/بعد» پخش می‌شود (روی هم افتادنِ صدا ممنوع) */
export function mutedFor(listen: "before" | "after", side: "before" | "after"): boolean {
  return listen !== side;
}

/** اندازه‌های پیش‌فرضِ «چند سایز» */
export function toggleKey(keys: string[], key: string): string[] {
  return keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key];
}


/** لحظهٔ ویدیو برای برچسبِ «قبل/بعد» (۱:۲۴) */
export function momentLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** لحظه‌های پیشنهادی برای نگاه کردن به نورِ ویدیو: اول، یک‌چهارم، وسط، سه‌چهارم و آخر؛ دور از لبه‌ها (تصویرِ سیاهِ ابتدا و انتها نیاید) و روی نیم‌ثانیه */
export function quickMoments(duration: number): { label: string; t: number }[] {
  if (!(duration > 1)) return [];
  const at = (f: number) => Math.round(Math.max(0.2, Math.min(duration - 0.4, duration * f)) * 2) / 2;
  return [
    { label: "اول", t: at(0.03) },
    { label: "یک‌چهارم", t: at(0.25) },
    { label: "وسط", t: at(0.5) },
    { label: "سه‌چهارم", t: at(0.75) },
    { label: "آخر", t: at(0.97) },
  ];
}
