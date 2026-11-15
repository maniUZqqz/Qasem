/**
 * پیگیریِ کارهای در حالِ انجامِ ادیتورِ عکس — بدونِ فشار به سرور (بازبینیِ ۱۴ آبان).
 *
 * قبلاً تا وقتی یک کار «منتظرِ سرورِ پردازش» بود (سرور خاموش) صفحه هر ۳ ثانیه فهرست یا عکس را می‌خواند، حتی در تبِ پنهان
 * (۱۱۸۹ درخواست تا ۱۱۴ کیلوبایت در سه روز). حالا:
 *   • تبِ پنهان ⇒ هیچ درخواستی؛ با برگشتنِ تب فوراً یک دور و دوباره از ۳ ثانیه.
 *   • فقط وقتی همهٔ کارها «منتظرِ سرورِ پردازش»اند و چیزی عوض نشده ⇒ فاصله ۳ ← ۱۵ ← ۶۰ ثانیه؛ هر تغییری فاصله را به ۳ برمی‌گرداند.
 *   • کارِ در حالِ اجرا روی سرورِ سایت همیشه ۳ ثانیه (چند ثانیه‌ای تمام می‌شود).
 * منطق «خالص» است (محیط تزریق می‌شود) تا بی مرورگر با node آزموده شود: tests/photo-audit.test.ts.
 */
export const POLL_STEPS_MS = [3000, 15000, 60000] as const;

export type PollEnv = {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  hidden: () => boolean;
  /** وقتی تب دوباره دیده شد صدا زده می‌شود؛ ⇐ لغوِ اشتراک */
  onVisible: (cb: () => void) => () => void;
};

export type TickResult = {
  /** وضعیتِ چیزی نسبت به دورِ قبل عوض شد؟ */
  changed: boolean;
  /** همهٔ کارهای در حالِ انتظار فقط منتظرِ سرورِ پردازش‌اند؟ (فقط آن‌وقت فاصله بلند می‌شود) */
  waitingOnly: boolean;
  /** دیگر چیزی برای پیگیری نمانده */
  stop?: boolean;
};

/** پلهٔ بعدیِ فاصله: بلند شدن فقط وقتی «بی‌تغییر و فقط منتظرِ سرورِ پردازش» است؛ هر چیزِ دیگر ⇐ ۳ ثانیه. */
export function nextStep(step: number, r: TickResult, steps: readonly number[] = POLL_STEPS_MS): number {
  if (r.changed || !r.waitingOnly) return 0;
  return Math.min(step + 1, steps.length - 1);
}

type EditLike = { state: string; needs_node?: boolean };

/** این کار فقط منتظرِ سرورِ پردازش است؟ (روی سرورِ سایت اجرا نمی‌شود) */
export function isWaitingOnNode(e: EditLike): boolean {
  return e.state === "NODE" || (e.state === "QUEUED" && !!e.needs_node);
}

/** اثرِ انگشتِ وضعیتِ یک نسخه برای تشخیصِ «چیزی عوض شد؟» */
export function edgeKey(e: { state: string; progress?: number; message?: string; error?: string }): string {
  return `${e.state}|${Math.round((e.progress ?? 0) * 100)}|${e.message ?? ""}|${e.error ?? ""}`;
}

export class BackoffPoller {
  step = 0;
  ticks = 0;
  private handle: unknown = null;
  private stopped = false;
  private running = false;
  private unsub: (() => void) | null = null;

  constructor(
    private readonly tick: () => Promise<TickResult>,
    private readonly env: PollEnv,
    private readonly steps: readonly number[] = POLL_STEPS_MS,
  ) {}

  start(): void {
    this.stopped = false;
    this.unsub = this.env.onVisible(() => this.wake());
    this.schedule();
  }

  stop(): void {
    this.stopped = true;
    if (this.handle !== null) this.env.clearTimeout(this.handle);
    this.handle = null;
    this.unsub?.();
    this.unsub = null;
  }

  /** تب دوباره دیده شد: فوراً یک دور و از پلهٔ اول */
  wake(): void {
    if (this.stopped || this.running) return;
    this.step = 0;
    if (this.handle !== null) this.env.clearTimeout(this.handle);
    this.handle = null;
    this.schedule(0);
  }

  /** فاصلهٔ دورِ بعدی (برای نمایش و آزمون) */
  get delay(): number {
    return this.steps[this.step] ?? this.steps[this.steps.length - 1];
  }

  private schedule(ms?: number): void {
    if (this.stopped || this.env.hidden()) return; // تبِ پنهان: منتظرِ wake می‌مانیم
    this.handle = this.env.setTimeout(() => void this.run(), ms ?? this.delay);
  }

  private async run(): Promise<void> {
    this.handle = null;
    if (this.stopped) return;
    if (this.env.hidden()) return; // در فاصله‌ی انتظار پنهان شد
    this.running = true;
    let r: TickResult = { changed: false, waitingOnly: false };
    try {
      r = await this.tick();
    } catch {
      /* شبکه: دورِ بعد، با همان پله */
      r = { changed: false, waitingOnly: true };
      this.ticks += 1;
      this.running = false;
      this.schedule();
      return;
    }
    this.ticks += 1;
    this.running = false;
    if (this.stopped) return;
    if (r.stop) {
      this.stop();
      return;
    }
    this.step = nextStep(this.step, r, this.steps);
    this.schedule();
  }
}

/** محیطِ واقعیِ مرورگر */
export function browserPollEnv(): PollEnv {
  return {
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (h) => window.clearTimeout(h as number),
    hidden: () => typeof document !== "undefined" && document.hidden,
    onVisible: (cb) => {
      const f = () => {
        if (!document.hidden) cb();
      };
      document.addEventListener("visibilitychange", f);
      return () => document.removeEventListener("visibilitychange", f);
    },
  };
}
