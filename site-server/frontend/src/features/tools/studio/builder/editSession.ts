/**
 * «ذخیرهٔ حینِ نوشتن»: هر بار که کاربر روی بوم تایپ می‌کند، بعد از ۶۰۰ میلی‌ثانیه مکث (و دست‌کم هر ۵ ثانیه، حتی اگر مکثی نباشد)
 * متنِ در حالِ نوشتن به سند می‌رسد، بی‌این‌که ویرایش تمام شود؛ پس بازکردنِ دوباره یا بستنِ زبانه چیزی را از دست نمی‌دهد.
 * زمان‌سنج تزریق می‌شود تا آزمون بی‌مرورگر بدود.
 */
export type Timers = {
  set: (fn: () => void, ms: number) => number;
  clear: (id: number) => void;
  now: () => number;
};

export const DEBOUNCE_MS = 600;
export const MAX_WAIT_MS = 5000;

export class EditSession {
  private timer: number | null = null;
  private firstAt = 0;

  constructor(
    private readonly flush: () => void,
    private readonly t: Timers,
    readonly debounceMs: number = DEBOUNCE_MS,
    readonly maxWaitMs: number = MAX_WAIT_MS,
  ) {}

  /** هر رویدادِ `input`. */
  input(): void {
    const now = this.t.now();
    if (this.firstAt === 0) this.firstAt = now;
    if (this.timer !== null) this.t.clear(this.timer);
    const left = Math.max(0, this.firstAt + this.maxWaitMs - now);
    this.timer = this.t.set(() => this.fire(), Math.min(this.debounceMs, left));
  }

  private fire(): void {
    this.timer = null;
    this.firstAt = 0;
    this.flush();
  }

  /** همین حالا (مثلاً هنگامِ بستنِ زبانه). */
  flushNow(): void {
    this.cancel();
    this.flush();
  }

  cancel(): void {
    if (this.timer !== null) this.t.clear(this.timer);
    this.timer = null;
    this.firstAt = 0;
  }

  get pending(): boolean {
    return this.timer !== null;
  }
}

export function browserTimers(): Timers {
  return {
    set: (fn, ms) => window.setTimeout(fn, ms),
    clear: (id) => window.clearTimeout(id),
    now: () => Date.now(),
  };
}
