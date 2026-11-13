import { Component, Suspense, lazy, type ComponentType, type ErrorInfo, type ReactNode } from "react";

import { Spinner } from "./ui";

/**
 * بارِ تنبلِ یک صفحه یا بخشِ سنگین (ویرایشگرِ دستیِ ویدیو، ویرایشگرِ عکس، نمایشگرِ سه‌بعدی…).
 *
 * چرا: همهٔ پنل یک فایلِ جاوااسکریپتِ ~۳٫۵ مگابایتی بود (حدود ۱٫۱ مگابایتِ فشرده)؛ هر ورود به پنل باید همه را می‌گرفت و تجزیه می‌کرد، حتی برای کسی که فقط
 * فهرستِ محصول‌ها را می‌خواست. حالا بخش‌های سنگین فقط وقتی که واقعاً لازم‌اند بار می‌شوند.
 *
 * - `Suspense` و کارتِ «در حالِ بارگیری» همین‌جا داخلِ کامپوننتِ برگشتی است؛ جای استفاده فرقی با قبل ندارد: `<PhotoEditorPage />`.
 * - اگر فایلِ تکه بعد از انتشارِ نسخهٔ تازه دیگر روی سرور نبود (تبِ قدیمیِ باز)، یک بار صفحه خودکار تازه می‌شود؛ بار دوم خطا همان‌طور که هست بالا می‌آید.
 */
const RELOAD_KEY = "nm.chunk-reload-at";

function reloadOnce(err: unknown): Promise<never> {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
    if (Date.now() - last > 20_000) {
      sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
      window.location.reload();
      return new Promise<never>(() => undefined); // تا لحظهٔ تازه‌شدن همان کارتِ بارگیری می‌ماند
    }
  } catch {
    /* حافظهٔ مرورگر بسته است؛ خطا را بالا بده */
  }
  return Promise.reject(err);
}

export function LazyFallback({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm" style={{ color: "var(--text-3)" }} role="status" data-testid="lazy-loading">
      <Spinner size={18} /> {label}
    </div>
  );
}

/** اگر بارگیریِ تکه (قطعِ اینترنت…) یا خودِ بخش خطا داد، به‌جای صفحهٔ سفید یک پیامِ فارسی با دکمهٔ تازه‌سازی نشان می‌دهد */
class LazyBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error("[lazyPage]", err, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="mx-auto my-12 max-w-md rounded-xl border p-5 text-center text-sm" style={{ borderColor: "var(--line)", color: "var(--text-2)" }} role="alert" data-testid="lazy-failed">
        <p>این بخش باز نشد (شاید اینترنت قطع شده یا نسخهٔ تازه‌ای آمده است).</p>
        <button type="button" className="mt-3 rounded-lg border px-3 py-1.5" style={{ borderColor: "var(--line)" }} onClick={() => window.location.reload()}>
          تازه‌سازیِ صفحه
        </button>
      </div>
    );
  }
}

export function lazyPage<P extends object>(load: () => Promise<{ default: ComponentType<P> }>, label = "در حالِ بارگیری…") {
  const Lazy = lazy(() => load().catch(reloadOnce));
  return function LazyPage(props: P) {
    const Inner = Lazy as unknown as ComponentType<P>;
    return (
      <LazyBoundary>
        <Suspense fallback={<LazyFallback label={label} />}>
          <Inner {...props} />
        </Suspense>
      </LazyBoundary>
    );
  };
}
