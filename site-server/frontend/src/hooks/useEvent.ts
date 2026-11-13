import { useCallback, useRef } from "react";

/**
 * تابعی با «هویتِ ثابت» که همیشه آخرین نسخهٔ `fn` را صدا می‌زند (مثلِ useEvent ریاکت).
 * برای دادنِ callback به فرزندهای `React.memo`: هر رندر یک `fn` تازه می‌سازد ولی فرزند همان تابعِ ثابت را می‌بیند و بی‌دلیل دوباره ساخته نمی‌شود.
 * فقط برای کارهای «رویداد‌محور» (کلیک، کشیدن)؛ نه برای چیزی که هنگامِ رندر صدا زده می‌شود.
 */
export function useEvent<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  ref.current = fn;
  return useCallback((...args: A) => ref.current(...args), []);
}

/**
 * همان کار برای یک «بستهٔ» callback ها: کلیدها از رندرِ اول ثابت می‌مانند، هر کدام به آخرین نسخهٔ خودش می‌رسد و هویتِ بسته عوض نمی‌شود.
 */
export function useStableFns<T extends Record<string, (...args: never[]) => unknown>>(fns: T): T {
  const ref = useRef(fns);
  ref.current = fns;
  const out = useRef<T | null>(null);
  if (out.current === null) {
    const made: Record<string, unknown> = {};
    for (const k of Object.keys(fns)) made[k] = (...args: unknown[]) => (ref.current[k] as (...a: unknown[]) => unknown)(...args);
    out.current = made as T;
  }
  return out.current;
}
