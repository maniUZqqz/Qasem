/**
 * تامنیل‌ساز — تاریخچه و هشدارها (منطقِ خالص؛ آزمون: tests/photo-audit.test.ts).
 *
 * بازبینیِ ۱۴ آبان: تاریخچه ۱۲ کارت بود و روی هر کدام همان دو هشدارِ یکسان تکرار می‌شد. حالا:
 *   • روی گوشی فقط آخرین ۴ کارت و دکمهٔ «نمایشِ بیشتر»؛
 *   • هشداری که روی چند نسخهٔ یک فهرست یکی است یک بار بالای فهرست (با شمارش) می‌آید، نه روی هر کارت.
 */
import type { ThumbItem } from "./api";

export const HISTORY_PHONE_LIMIT = 4;

export type SharedWarning = { text: string; count: number };

/** هشدارهای مشترکِ فهرست (در ≥۲ نسخه یکی‌اند) + هشدارِ ویژهٔ هر نسخه. فهرستِ تک‌نسخه‌ای دست‌نخورده می‌ماند. */
export function splitWarnings(items: Pick<ThumbItem, "id" | "warnings">[]): { shared: SharedWarning[]; own: Map<number, string[]> } {
  const count = new Map<string, number>();
  for (const it of items) for (const w of new Set(it.warnings ?? [])) count.set(w, (count.get(w) ?? 0) + 1);
  const sharedTexts = new Set([...count].filter(([, n]) => n >= 2 && items.length >= 2).map(([w]) => w));
  const own = new Map<number, string[]>();
  for (const it of items) own.set(it.id, [...new Set(it.warnings ?? [])].filter((w) => !sharedTexts.has(w)));
  const shared = [...sharedTexts].map((text) => ({ text, count: count.get(text) ?? 0 }));
  return { shared, own };
}

/** روی گوشی تاریخچه کوتاه می‌شود مگر کاربر «نمایشِ بیشتر» بزند */
export function visibleHistory<T>(items: T[], opts: { phone: boolean; expanded: boolean }): { shown: T[]; hidden: number } {
  if (!opts.phone || opts.expanded || items.length <= HISTORY_PHONE_LIMIT) return { shown: items, hidden: 0 };
  return { shown: items.slice(0, HISTORY_PHONE_LIMIT), hidden: items.length - HISTORY_PHONE_LIMIT };
}
