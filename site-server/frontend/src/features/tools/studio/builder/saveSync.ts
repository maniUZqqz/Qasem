/**
 * منطقِ خالصِ «ذخیرهٔ خودکار» ویرایشگرِ دیداری (بی‌React و بی‌مرورگر تا با آزمونِ ساده سنجیده شود).
 *
 * سه چیز در یک نشان جمع می‌شود: ذخیرهٔ سند، نوشتنِ هنوز-فرستاده‌نشده روی بوم، و ذخیرهٔ پوسته/منو؛
 * شکست هر کدام «ذخیره نشد» می‌شود و با فاصلهٔ ۲، ۵، ۱۵ ثانیه (و از آن به بعد هر ۱۵ ثانیه) دوباره تلاش می‌شود.
 */
export type SaveState = "saved" | "saving" | "error" | "conflict";

/** فاصلهٔ تلاش‌های دوباره پس از شکست (میلی‌ثانیه). از سومی به بعد همان ۱۵ ثانیه تکرار می‌شود. */
export const RETRY_MS = [2000, 5000, 15000] as const;

export function retryDelay(attempt: number): number {
  const i = Math.min(Math.max(Math.floor(attempt) || 0, 0), RETRY_MS.length - 1);
  return RETRY_MS[i];
}

export type ChipInput = { save: SaveState; typing: boolean; themePending: boolean; themeFailed: boolean };

/** نشانِ بالای ویرایشگر: بدترین وضعیتِ هر سه کار. */
export function chipState(p: ChipInput): SaveState {
  if (p.save === "conflict") return "conflict";
  if (p.save === "error" || p.themeFailed) return "error";
  if (p.save === "saving" || p.typing || p.themePending) return "saving";
  return "saved";
}

/** هر چیزی جز «ذخیره شد» یعنی کارِ ذخیره‌نشده هست؛ بستنِ زبانه باید هشدار بدهد. */
export function hasUnsaved(state: SaveState): boolean {
  return state !== "saved";
}

export function chipText(state: SaveState, dirty: boolean, themeFailed: boolean): string {
  if (state === "error" && themeFailed) return "ذخیرهٔ پوسته و منو نشد؛ دوباره تلاش می‌شود";
  return {
    saved: dirty ? "پیش‌نویس ذخیره شد" : "منتشر شده",
    saving: "در حالِ ذخیره…",
    error: "ذخیره نشد؛ دوباره تلاش می‌شود",
    conflict: "جای دیگری هم باز است",
  }[state];
}

/** سقفِ بدنهٔ fetch با keepalive در مرورگرها ۶۴ کیلوبایت است؛ بزرگ‌تر از این باید راهِ معمولی برود. */
export const KEEPALIVE_LIMIT = 60000;

export function canKeepalive(body: string): boolean {
  // طولِ بایتی، نه تعدادِ نویسه (فارسی دوبایتی است)
  let bytes = 0;
  for (let i = 0; i < body.length; i += 1) {
    const c = body.charCodeAt(i);
    bytes += c < 0x80 ? 1 : c < 0x800 ? 2 : 3;
    if (bytes > KEEPALIVE_LIMIT) return false;
  }
  return true;
}
