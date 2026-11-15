/**
 * کتابخانهٔ عکسِ ادیتور — منطقِ خالص (بی React) تا بی مرورگر آزموده شود: tests/photo-audit.test.ts.
 *
 * بازبینیِ ۱۴ آبان: با ۴۹ عکس کتابخانه ۵۰۰۰ تا ۱۰۰۰۰ پیکسل بلند می‌شد و پنلِ کار را به ته‌ی صفحه می‌راند؛ هر کارت هم تا دو برچسبِ
 * زردِ هشدار داشت. حالا فقط «آخرین ۱۲» با «نمایش بیشتر» و جستجو، و روی هر کارت حداکثر یک برچسب (فقط برای عکسِ واقعی).
 */
import type { Asset, Finding } from "./api";

export const LIB_PAGE = 12;

/** از مهم به کم‌اهمیت؛ «plain_bg» خبرِ خوب است و فقط وقتی هیچ هشداری نیست نشان داده می‌شود */
const PRIORITY = ["dark", "bright", "clipped", "flat", "cast", "blurry", "noisy", "small", "huge"] as const;

/** تنها برچسبِ کارت: مهم‌ترین هشدار؛ برای طرحِ گرافیکی (اسلاید) هرگز */
export function primaryFinding(asset: Pick<Asset, "findings" | "facts">): Finding | null {
  if (asset.facts && asset.facts.graphic === true) return null;
  const list = asset.findings ?? [];
  for (const k of PRIORITY) {
    const f = list.find((x) => x.what === k);
    if (f) return f;
  }
  return list.find((x) => x.what === "plain_bg") ?? null;
}

export function findingLabel(f: Finding): string {
  return f.note.split(" (")[0];
}

/** «ي» و «ك» عربی و فاصلهٔ مجازی را یکی می‌کند تا جستجوی فارسی خطا نکند */
export function normFa(s: string): string {
  return (s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/[‌‏]/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
}

export function filterAssets<T extends Pick<Asset, "title" | "source_label" | "product_name">>(assets: T[], query: string): T[] {
  const q = normFa(query);
  if (!q) return assets;
  return assets.filter((a) => normFa(`${a.title} ${a.source_label} ${a.product_name ?? ""}`).includes(q));
}

export function pageAssets<T>(assets: T[], limit: number): { shown: T[]; rest: number } {
  const n = Math.max(1, limit);
  return { shown: assets.slice(0, n), rest: Math.max(0, assets.length - n) };
}
