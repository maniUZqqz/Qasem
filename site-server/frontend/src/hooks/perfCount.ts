/**
 * شمارندهٔ رندرِ توسعه‌ای (برای سنجشِ «چند بار این بخش در ثانیه دوباره ساخته می‌شود»).
 *
 * خاموش است مگر این‌که صفحه با `window.__nmPerf = {}` (مثلاً از آزمونِ مرورگر یا کنسول: `window.__nmPerf = {}`) شروع کرده باشد؛
 * خاموش بودن یعنی فقط یک خواندنِ ویژگی، پس هزینه‌ای برای کاربر ندارد. شمارنده‌ها در `window.__nmPerf[نام]` جمع می‌شوند.
 */
type PerfBag = Record<string, number>;

export function countRender(name: string, by = 1): void {
  if (typeof window === "undefined") return;
  const bag = (window as unknown as { __nmPerf?: PerfBag }).__nmPerf;
  if (bag) bag[name] = (bag[name] ?? 0) + by;
}
