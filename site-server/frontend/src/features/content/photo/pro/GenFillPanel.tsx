import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import type { GenFillResult, GenFillStatus } from "../api";
import { GenFillError, cancelGenFill, isAbort, runGenFill } from "./genfill";
import "./genfill.css";

export type GenFillPanelProps = {
  storeId: string;
  /** عکسِ کتابخانه‌ای که پروژه به آن تعلق دارد */
  assetId: number;
  /** PNG ِ بومِ فعلی (ترکیبِ لایه‌ها)، حداکثر ۲۰۴۸ پیکسل */
  getImage: () => Promise<Blob>;
  /** PNG ِ خاکستری هم‌اندازهٔ تصویر (سفید = پر شود)؛ null = هنوز ناحیه‌ای انتخاب نشده */
  getMask: () => Promise<Blob | null>;
  /** نتیجه آماده شد: result.asset (RGBA) را در result.layer {cx,cy,w} به‌صورتِ لایهٔ تصویری اضافه کنید */
  onResult: (result: GenFillResult) => void;
  disabled?: boolean;
  /** میزبان می‌خواهد بداند کاری در جریان است (مثلاً برای قفلِ ابزارها) */
  onBusyChange?: (busy: boolean) => void;
  /**
   * اگر میزبان شناسهٔ کار را نگه می‌دارد (برای ادامه پس از بازکردنِ دوبارهٔ صفحه): با شروعِ کار صدا می‌خورد
   * و با پایانش null. در این حالت بستنِ پنل کارِ سمتِ سرور را لغو نمی‌کند.
   */
  onJobChange?: (job: string | null) => void;
  /** ادامهٔ کارِ ثبت‌شده به‌جای شروعِ تازه */
  resumeJob?: string | null;
};

type Phase = "idle" | "preparing" | "running";

const PLACEHOLDER = "چه چیزی جایش بگذارم؟ (خالی = حذفِ شیء و پر کردنِ جا با پس‌زمینه)";

export default function GenFillPanel(props: GenFillPanelProps) {
  const { storeId, assetId, onResult, disabled, onBusyChange, onJobChange, resumeJob } = props;
  const [prompt, setPrompt] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState<GenFillStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ seconds: number | null } | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const jobRef = useRef<string>("");
  const propsRef = useRef(props);
  propsRef.current = props;
  const busy = phase !== "idle";

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  // شمارندهٔ زمان تا کار تمام شود
  useEffect(() => {
    if (phase !== "running") return;
    const t0 = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [phase]);

  const track = useCallback(
    async (args: { image: Blob; mask: Blob } | null, resume?: string) => {
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setPhase("running");
      try {
        const res = await runGenFill(
          storeId,
          { assetId, image: args?.image ?? new Blob(), mask: args?.mask ?? new Blob(), prompt: prompt.trim() },
          {
            signal: ctrl.signal,
            resumeJob: resume,
            keepJobOnAbort: !!propsRef.current.onJobChange,
            onJob: (j) => {
              jobRef.current = j;
              propsRef.current.onJobChange?.(j);
            },
            onUpdate: setStatus,
          },
        );
        propsRef.current.onJobChange?.(null);
        jobRef.current = "";
        setDone({ seconds: res.seconds ?? null });
        propsRef.current.onResult(res);
      } catch (err) {
        if (isAbort(err)) return; // انصراف/بسته‌شدنِ پنل: پیامی لازم نیست
        propsRef.current.onJobChange?.(null);
        jobRef.current = "";
        setError(err instanceof GenFillError ? err.message : errorMessage(err));
      } finally {
        // فقط اجرای «جاری» وضعیت را به بی‌کار برمی‌گرداند (در StrictMode ِ توسعه اجرای قبلیِ لغوشده نباید اجرای تازه را خاموش کند)
        if (abortRef.current === ctrl) {
          abortRef.current = null;
          setPhase("idle");
          setStatus(null);
        }
      }
    },
    [storeId, assetId, prompt],
  );

  const run = async () => {
    if (busy || disabled) return;
    setError(null);
    setDone(null);
    setPhase("preparing");
    let image: Blob;
    let mask: Blob | null;
    try {
      [image, mask] = await Promise.all([propsRef.current.getImage(), propsRef.current.getMask()]);
    } catch (err) {
      setPhase("idle");
      setError(`آماده‌کردنِ تصویر انجام نشد: ${err instanceof Error ? err.message : "خطای نامشخص"}`);
      return;
    }
    if (!mask) {
      setPhase("idle");
      setError("اول جایی را که باید پر شود با قلم یا انتخاب مشخص کنید.");
      return;
    }
    await track({ image, mask });
  };

  // ادامهٔ کارِ ثبت‌شده (فقط یک بار، هنگامِ بالا آمدنِ پنل)
  const resumed = useRef(false);
  useEffect(() => {
    if (resumeJob && !resumed.current && !abortRef.current) {
      resumed.current = true;
      void track(null, resumeJob);
    }
  }, [resumeJob, track]);

  const cancel = () => {
    const job = jobRef.current;
    abortRef.current?.abort();
    if (job) {
      void cancelGenFill(storeId, job);
      propsRef.current.onJobChange?.(null);
      jobRef.current = "";
    }
    setPhase("idle");
    setStatus(null);
  };

  // بستنِ پنل: پرسیدن را قطع کن؛ کارِ سمتِ سرور فقط وقتی میزبان آن را نگه نمی‌دارد لغو می‌شود
  useEffect(
    () => () => {
      const job = jobRef.current;
      abortRef.current?.abort();
      abortRef.current = null;
      resumed.current = false; // (StrictMode: سوارِ دوباره = ادامهٔ همان کار)
      if (job && !propsRef.current.onJobChange) void cancelGenFill(storeId, job);
    },
    [storeId],
  );

  const waiting = phase === "running" && status?.state === "QUEUED" && status.online === false;
  const pct = Math.round(Math.min(1, Math.max(0, status?.progress ?? 0)) * 100);

  return (
    <div className="gf-root" dir="rtl">
      <div className="gf-title">پرکردنِ هوشمند</div>
      <p className="gf-hint">
        جایی را که می‌خواهید عوض یا حذف شود با قلم یا انتخاب مشخص کنید؛ نتیجه به‌صورتِ یک لایهٔ تازه رویِ همان جا می‌نشیند و
        عکسِ اصلی دست‌نخورده می‌ماند.
      </p>
      <label className="gf-label" htmlFor="gf-prompt">
        چه چیزی جایش بگذارم؟
      </label>
      <textarea
        id="gf-prompt"
        className="gf-input"
        rows={3}
        maxLength={300}
        value={prompt}
        placeholder={PLACEHOLDER}
        disabled={busy || disabled}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") void run();
        }}
      />
      <p className="gf-hint">
        مدلِ ساخت انگلیسی را بهتر می‌فهمد؛ برای نتیجهٔ دقیق‌تر توضیح را انگلیسی بنویسید (مثلاً <bdi dir="ltr">blue sky</bdi>). خالی
        بگذارید تا شیء حذف و جایش با پس‌زمینهٔ اطراف پر شود.
      </p>
      <div className="gf-actions">
        <button type="button" className="gf-btn primary" onClick={() => void run()} disabled={busy || disabled}>
          اجرا
        </button>
        <button type="button" className="gf-btn" onClick={cancel} disabled={!busy}>
          انصراف
        </button>
      </div>

      {phase === "preparing" && (
        <div className="gf-progress" role="status">
          <Spinner size={16} />
          <span>در حالِ آماده‌کردنِ تصویر…</span>
        </div>
      )}
      {phase === "running" && (
        <div className={`gf-progress${waiting ? " is-waiting" : ""}`} role="status" aria-live="polite">
          <div className="gf-progress-line">
            <Spinner size={16} />
            <span className="gf-progress-text">{status?.message || "در حالِ ارسال…"}</span>
            <span className="gf-elapsed" aria-label="زمانِ گذشته">
              {fa(elapsed)} ثانیه
            </span>
          </div>
          {!waiting && (
            <div className="gf-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <i style={{ width: `${Math.max(4, pct)}%` }} />
            </div>
          )}
          {waiting && (
            <p className="gf-sub">
              می‌توانید همین‌جا منتظر بمانید یا «انصراف» را بزنید؛ تا روشن‌شدنِ سرورِ پردازش هیچ چیزی در عکس عوض نمی‌شود.
            </p>
          )}
        </div>
      )}
      {error && (
        <p className="gf-msg bad" role="alert">
          {error}
        </p>
      )}
      {done && !busy && (
        <p className="gf-msg ok" role="status">
          انجام شد{done.seconds ? ` (${fa(Math.round(done.seconds))} ثانیه)` : ""}؛ لایهٔ «پرکردن هوشمند» به پروژه اضافه شد. اگر
          نتیجه را نپسندیدید دوباره «اجرا» را بزنید تا نمونهٔ دیگری ساخته شود.
        </p>
      )}
    </div>
  );
}
