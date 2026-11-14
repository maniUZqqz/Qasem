import { normalizePath } from "./tabTitle";
import { PAGES, pageHref, type PanelPage } from "./registry";

/**
 * «شاید این صفحه‌ها را می‌خواستید» برای صفحهٔ «پیدا نشد».
 *
 * آدرس‌های اشتباه معمولاً یا قدیمی‌اند یا غلطِ تایپی (`/stores/34/analytic`)؛ از
 * روی تکه‌های آدرس، نزدیک‌ترین صفحه‌های منو را پیدا می‌کنیم. بدون React، تا بی
 * مرورگر آزمون شود.
 */

export type Suggestion = { key: string; label: string; href: string };

/** فاصلهٔ ویرایشی (درج/حذف/جایگزینی) — رشته‌ها کوتاه‌اند، پس نسخهٔ ساده کافی است. */
export function editDistance(a: string, b: string): number {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) {
      row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = row;
  }
  return prev[b.length];
}

const GENERIC = new Set(["stores", "store", "products", "product", "tools", "panel", "admin"]);

/** تکه‌های معنادارِ آدرس: بدون شناسه‌های عددی و واژه‌های عمومی، با شکستن روی «-» و «_». */
function tokensOf(pathname: string): string[] {
  const out: string[] = [];
  for (const seg of normalizePath(pathname).split("/")) {
    let s = seg;
    try {
      s = decodeURIComponent(seg);
    } catch {
      /* آدرسِ خراب — همان‌طور که هست */
    }
    for (const t of s.toLowerCase().split(/[-_.]+/)) {
      if (t.length >= 3 && !/^\d+$/.test(t) && !GENERIC.has(t)) out.push(t);
    }
  }
  return out;
}

function scoreToken(token: string, seg: string): number {
  if (seg === token) return 3;
  if (token.length < 4 || seg.length < 4) return 0;
  if (seg.includes(token) || token.includes(seg)) return 2;
  return editDistance(seg, token) <= (token.length >= 7 ? 2 : 1) ? 2 : 0;
}

export function suggestPages(
  pathname: string,
  opts: {
    storeId: string | null;
    isStaff: boolean;
    /** صفحه‌ی خاموش‌شده توسط ادمین نباید پیشنهاد شود (`useFlags().pageEnabled`). */
    enabled?: (page: PanelPage) => boolean;
    limit?: number;
  },
): Suggestion[] {
  const tokens = tokensOf(pathname);
  if (!tokens.length) return [];
  const limit = opts.limit ?? 5;

  const scored: { s: Suggestion; score: number; order: number }[] = [];
  PAGES.forEach((page, order) => {
    if (page.menu === false || page.external) return;
    if (page.staffOnly && !opts.isStaff) return;
    if (typeof page.to === "function" && !opts.storeId) return;
    if (opts.enabled && !opts.enabled(page)) return;

    const href = pageHref(page, opts.storeId);
    const segs = [
      ...href.split("/").filter((p) => p && !/^\d+$/.test(p)),
      ...page.key.split("_"),
    ].map((p) => p.toLowerCase());

    let score = 0;
    for (const t of tokens) for (const seg of segs) score = Math.max(score, scoreToken(t, seg));
    if (score > 0) scored.push({ s: { key: page.key, label: page.label, href }, score, order });
  });

  scored.sort((a, b) => b.score - a.score || a.order - b.order);
  const seen = new Set<string>();
  const out: Suggestion[] = [];
  for (const { s } of scored) {
    if (seen.has(s.href)) continue;
    seen.add(s.href);
    out.push(s);
    if (out.length >= limit) break;
  }
  return out;
}
