import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";

/**
 * «سرِ پخش» (زمانِ فعلیِ تایم‌لاین) بیرون از stateِ ریاکت.
 *
 * چرا: پخش هر ~۷۰ میلی‌ثانیه و کشیدنِ سرِ پخش با ماوس هر چند میلی‌ثانیه زمان را عوض می‌کنند. اگر زمان `useState`ِ فضای کار باشد،
 * هر تیک کلِ فضای کار (سطل، مانیتور، بازرس، تایم‌لاین و همهٔ ترک‌ها) را دوباره می‌سازد و ادیتور کند می‌شود. این‌جا زمان یک «انباره» است:
 * فقط چیزهایی که واقعاً زمان را نشان می‌دهند (مانیتور، خطِ سرِ پخش، مقدارهای کلیدفریمیِ بازرس) مشترک می‌شوند و بقیه دست نمی‌خورند.
 * کارهایی که فقط لحظهٔ رویداد زمان را لازم دارند (تقسیم، نشانگر…) با `get()` می‌خوانند و اصلاً مشترک نمی‌شوند.
 */
export type Playhead = {
  get: () => number;
  /** مقدارِ برابر هیچ خبری نمی‌دهد (مثلِ setState) */
  set: (t: number) => void;
  subscribe: (fn: () => void) => () => void;
};

export function createPlayhead(initial = 0): Playhead {
  let t = initial;
  const subs = new Set<() => void>();
  return {
    get: () => t,
    set: (v: number) => {
      if (Object.is(v, t)) return;
      t = v;
      subs.forEach((f) => f());
    },
    subscribe: (fn: () => void) => {
      subs.add(fn);
      return () => {
        subs.delete(fn);
      };
    },
  };
}

/** وقتی هیچ فضای کاری بالاتر نیست (آزمون/استفادهٔ مستقل) یک انبارهٔ ثابتِ صفر */
const FALLBACK: Playhead = createPlayhead(0);

export const PlayheadContext = createContext<Playhead>(FALLBACK);

/** خودِ انباره (برای `get()` در لحظهٔ رویداد یا `subscribe` دستی)؛ مشترکِ زمان نمی‌شود، پس رندر نمی‌خواهد */
export const usePlayheadStore = (): Playhead => useContext(PlayheadContext);

/** عددِ زمان؛ هر تغییرِ زمان این کامپوننت را دوباره می‌سازد (فقط جایی بزنید که واقعاً زمان نمایش می‌دهد) */
export function usePlayhead(): number {
  const ph = useContext(PlayheadContext);
  return useSyncExternalStore(ph.subscribe, ph.get, ph.get);
}

/**
 * مثلِ usePlayhead ولی حداکثر هر `minMs` میلی‌ثانیه یک بار (و همیشه با آخرین مقدار) — برای پنل‌های بزرگی که مقدارِ «در سرِ پخش» را فقط
 * نشان می‌دهند (بازرسِ قطعه/صدا/متن): هنگامِ پخش ۱۴ بار در ثانیه لازم نیست دوباره ساخته شوند؛ چشم فرقی نمی‌بیند.
 */
export function useThrottledPlayhead(minMs: number): number {
  const ph = useContext(PlayheadContext);
  const [t, setT] = useState(() => ph.get());
  useEffect(() => {
    let timer = 0;
    let last = 0;
    const fire = () => {
      timer = 0;
      last = performance.now();
      setT(ph.get());
    };
    const off = ph.subscribe(() => {
      if (timer) return;
      timer = window.setTimeout(fire, Math.max(0, minMs - (performance.now() - last)));
    });
    setT(ph.get());
    return () => {
      off();
      window.clearTimeout(timer);
    };
  }, [ph, minMs]);
  return t;
}
