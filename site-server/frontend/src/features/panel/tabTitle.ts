import { matchPath } from "react-router-dom";

import { PAGES, type PanelPage } from "./registry";

/**
 * عنوانِ تبِ مرورگر — از همان فهرستِ منوی پنل (`registry.ts`) ساخته می‌شود.
 *
 * تا پیش از این، همهٔ صفحه‌ها «NMarketing» بودند؛ با چند تبِ باز نمی‌شد فهمید
 * کدام تبِ کدام صفحه است، و تاریخچهٔ مرورگر هم فقط یک نام داشت. حالا:
 *
 *     «برچسبِ صفحه | نامِ فروشگاه | NMarketing»
 *
 * نامِ فروشگاه فقط برای صفحه‌های `/stores/:id/…` می‌آید (داشبورد و ابزارها
 * فروشگاهی ندارند). این فایل عمداً هیچ React ندارد، تا بی مرورگر آزمون شود.
 */

export const BRAND = "NMarketing";
export const NOT_FOUND_LABEL = "صفحه پیدا نشد";
export const NOT_FOUND_TITLE = `${NOT_FOUND_LABEL} | ${BRAND}`;

/** صفحه‌هایی که بیرون از قابِ پنل‌اند (ورود، ثبت‌نام، «چه چیزی تازه است») و در فهرستِ منو نیستند. */
export const PUBLIC_LABELS: Record<string, string> = {
  "/login": "ورود",
  "/register": "ثبت‌نام",
  "/forgot-password": "فراموشیِ رمز",
  "/reset-password": "تغییرِ رمز",
  "/changelog": "چه چیزی تازه است",
};

type Entry = { page: PanelPage; pattern: string; depth: number };

/** الگوی هر صفحه، با `:id` به‌جای شناسه: `/stores/:id/analytics`. صفحه‌ی جنگو (بیرونِ پنل) نمی‌آید. */
const ENTRIES: Entry[] = PAGES.filter((p) => !p.external).map((page) => {
  const pattern = typeof page.to === "function" ? page.to(":id") : page.to;
  return { page, pattern, depth: pattern.split("/").filter(Boolean).length };
});

/** `/stores/34/` ⇒ `/stores/34`؛ ریشه می‌ماند. */
export function normalizePath(pathname: string): string {
  const clean = (pathname || "/").split(/[?#]/)[0];
  return clean.length > 1 ? clean.replace(/\/+$/, "") || "/" : "/";
}

/**
 * صفحه‌ی منوی این آدرس، یا `null`.
 *
 * ۱) تطبیقِ کامل (اولینِ ثبت‌شده برنده است)؛ ۲) پیشوند، فقط برای صفحه‌هایی که
 * `end` ندارند — مثلاً `/growth/leads/12` ⇐ «جزئیات لید» و `/tools/3d/…` ⇐
 * «ویدیوی سه‌بعدی». صفحه‌ای که `end` دارد (فهرستِ فروشگاه، داشبورد، …) هرگز
 * پیشوند نمی‌شود، وگرنه آدرسِ غلطِ `/stores/34/xyz` «محصولات» می‌شد.
 */
export function registryPageFor(pathname: string): PanelPage | null {
  const path = normalizePath(pathname);
  const exact = ENTRIES.find((e) => matchPath({ path: e.pattern, end: true }, path));
  if (exact) return exact.page;

  let best: Entry | null = null;
  for (const e of ENTRIES) {
    if (e.page.end || e.pattern === "/") continue;
    if (!matchPath({ path: e.pattern, end: false }, path)) continue;
    // عمیق‌تر برنده است؛ در تساوی، آخریِ ثبت‌شده (مثلاً «جزئیات لید» بعد از «دیتابیس لیدها»)
    if (!best || e.depth >= best.depth) best = e;
  }
  return best ? best.page : null;
}

/** برچسبِ کوتاهِ صفحه (بدون «| NMarketing»)، یا `null` اگر آدرس هیچ صفحه‌ای نیست. */
export function pageLabelFor(pathname: string): string | null {
  const path = normalizePath(pathname);
  if (PUBLIC_LABELS[path]) return PUBLIC_LABELS[path];
  const page = registryPageFor(path);
  if (!page) return null;
  // «مشخصات» به‌تنهایی در تب معنا ندارد؛ زبانه‌های صفحهٔ محصول پیشوند می‌گیرند
  return page.section === "product" ? `محصول — ${page.label}` : page.label;
}

/** عنوانِ کاملِ تب. آدرسِ ناشناخته فقط «NMarketing» است — صفحهٔ «پیدا نشد» عنوانِ خودش را می‌گذارد. */
export function titleFor(pathname: string, storeName?: string | null): string {
  const path = normalizePath(pathname);
  const label = pageLabelFor(path);
  if (!label) return BRAND;
  const inStore = /^\/stores\/[^/]+/.test(path);
  return [label, inStore ? storeName : null, BRAND].filter(Boolean).join(" | ");
}
