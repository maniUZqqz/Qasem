import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import type { GenFillPreview, GenFillResult, GenFillStatus, GenFillTranslation } from "../api";
import { GenFillError, cancelGenFill, hasPersian, isAbort, previewTranslation, runGenFill, sendEnglishPrompt, validEnglish } from "./genfill";
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

/** وضعیتِ ترجمهٔ پیش‌نمایش (پیش از «اجرا») */
type TrView = { state: "idle" | "pending" | "ok" | "unavailable" | "failed"; label?: string; message?: string };

const PLACEHOLDER = "چه چیزی جایش بگذارم؟ (خالی = حذفِ شیء و پر کردنِ جا با پس‌زمینه)";
const SOURCE_LABEL: Record<string, string> = { auto: "ترجمهٔ خودکار", cache: "ترجمهٔ ذخیره‌شده", user: "نوشتهٔ شما" };

/** «ترجمهٔ خودکار با لوکال (gemma3:12b)» / «ترجمهٔ ذخیره‌شده» / «نوشتهٔ شما» */
const transLabel = (t: Pick<GenFillTranslation, "source" | "label">): string => {
  const base = SOURCE_LABEL[t.source] ?? "ترجمه";
  return t.label && t.source !== "user" ? `${base} (${t.label})` : base;
};

export default function GenFillPanel(props: GenFillPanelProps) {
  const { storeId, assetId, onResult, disabled, onBusyChange, onJobChange, resumeJob } = props;
  const [prompt, setPrompt] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState<GenFillStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ seconds: number | null; translation?: GenFillTranslation } | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // ترجمهٔ فارسی ⇒ انگلیسی: پیش‌نمایشِ ویرایش‌پذیر (همین متن به مدل می‌رود)
  const [en, setEn] = useState("");
  const [tr, setTr] = useState<TrView>({ state: "idle" });
  const [retry, setRetry] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  // کارِ منتظرِ ترجمه: کاربر می‌تواند همان‌جا انگلیسی بنویسد
  const [waitEn, setWaitEn] = useState("");
  const [waitBusy, setWaitBusy] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const jobRef = useRef<string>("");
  const propsRef = useRef(props);
  propsRef.current = props;
  const busy = phase !== "idle";
  const persian = hasPersian(prompt);

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

  // توضیحِ فارسی ⇒ (کمی بعد از آخرین نوشتن) ترجمهٔ پیش‌نمایش از سرور؛ ترجمهٔ قبلی برای متنِ تازه معنا ندارد
  useEffect(() => {
    setNote(null);
    setEn("");
    if (!persian) {
      setTr({ state: "idle" });
      return;
    }
    setTr({ state: "pending" });
    const ctrl = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const res: GenFillPreview = await previewTranslation(storeId, prompt.trim(), ctrl.signal);
        if (ctrl.signal.aborted) return;
        if (res.state === "ok" && res.en) {
          setEn(res.en);
          setTr({ state: "ok", label: res.cached ? "ترجمهٔ ذخیره‌شده" : transLabel({ source: res.source ?? "auto", label: res.label ?? "" }) });
        } else if (res.state === "none") {
          setTr({ state: "idle" });
        } else if (res.state === "pending") {
          setTr({ state: "unavailable", message: "ترجمه طول کشید؛ «ترجمهٔ دوباره» را بزنید یا انگلیسی را خودتان بنویسید." });
        } else {
          setTr({ state: res.state, message: res.message });
        }
      } catch (err) {
        if (isAbort(err) || ctrl.signal.aborted) return;
        setTr({ state: "unavailable", message: `ترجمهٔ خودکار انجام نشد: ${errorMessage(err)}` });
      }
    }, 700);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [prompt, persian, storeId, retry]);

  const track = useCallback(
    async (args: { image: Blob; mask: Blob; promptEn: string } | null, resume?: string) => {
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setPhase("running");
      try {
        const res = await runGenFill(
          storeId,
          { assetId, image: args?.image ?? new Blob(), mask: args?.mask ?? new Blob(), prompt: prompt.trim(), promptEn: args?.promptEn },
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
        setDone({ seconds: res.seconds ?? null, translation: res.translation });
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
          setWaitEn("");
        }
      }
    },
    [storeId, assetId, prompt],
  );

  const run = async () => {
    if (busy || disabled) return;
    setError(null);
    setDone(null);
    setNote(null);
    let promptEn = "";
    if (persian) {
      const cur = en.trim();
      if (cur) {
        if (!validEnglish(cur)) {
          setError("ترجمه باید فقط حرفِ لاتین داشته باشد (بدونِ حرفِ فارسی)؛ ویرایشش کنید.");
          return;
        }
        promptEn = cur;
      } else if (tr.state === "pending") {
        // ترجمه باید پیش از ساختن دیده شود؛ تا نیامده نمی‌فرستیم
        setNote("ترجمه هنوز در راه است؛ بعد از دیدنِ آن دوباره «اجرا» را بزنید.");
        return;
      }
      // ترجمه نشد (مترجم نیست) و انگلیسی هم ننوشته‌اید ⇒ کار در صف می‌ماند و به‌محضِ آماده‌شدنِ مترجم ترجمه می‌شود
    }
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
    await track({ image, mask, promptEn });
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

  // کارِ منتظرِ ترجمه: انگلیسیِ نوشتهٔ کاربر ⇒ کار همین حالا آزاد می‌شود
  const sendWaitEnglish = async () => {
    const job = jobRef.current;
    const text = waitEn.trim();
    if (!job || !validEnglish(text) || waitBusy) return;
    setWaitBusy(true);
    try {
      setStatus(await sendEnglishPrompt(storeId, job, text));
      setWaitEn("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWaitBusy(false);
    }
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

  const trs = status?.translation;
  const holding = phase === "running" && status?.state === "QUEUED" && trs?.state === "waiting";
  const waiting = phase === "running" && status?.state === "QUEUED" && status.online === false && !holding;
  const pct = Math.round(Math.min(1, Math.max(0, status?.progress ?? 0)) * 100);
  const enOk = en.trim() === "" || validEnglish(en);

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
        فارسی بنویسید؛ پیش از ساختن به انگلیسیِ تحت‌اللفظی ترجمه می‌شود (مدلِ ساخت انگلیسی را بهتر می‌فهمد) و ترجمه را همین‌جا
        می‌بینید و می‌توانید ویرایشش کنید. اگر انگلیسی بنویسید (مثلاً <bdi dir="ltr">blue sky</bdi>) ترجمه‌ای لازم نیست. خالی
        بگذارید تا شیء حذف و جایش با پس‌زمینهٔ اطراف پر شود.
      </p>

      {persian && (
        <div className="gf-tr" data-testid="gf-translation" data-state={tr.state}>
          <label className="gf-label" htmlFor="gf-en">
            ترجمه:
          </label>
          <input
            id="gf-en"
            dir="ltr"
            className={`gf-en${enOk ? "" : " is-bad"}`}
            type="text"
            maxLength={500}
            value={en}
            placeholder={tr.state === "pending" ? "در حالِ ترجمه…" : "English prompt"}
            aria-invalid={!enOk}
            disabled={busy || disabled}
            onChange={(e) => {
              setEn(e.target.value);
              setTr((t) => (t.state === "ok" ? { state: "ok", label: "ویرایش‌شده توسطِ شما" } : t));
            }}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") void run();
            }}
          />
          {tr.state === "pending" && (
            <p className="gf-sub gf-tr-line" role="status">
              <Spinner size={12} /> در حالِ ترجمه…
            </p>
          )}
          {tr.state === "ok" && (
            <p className="gf-sub gf-tr-line" role="status">
              {tr.label ? `${tr.label} — ` : ""}این متن به مدل فرستاده می‌شود؛ اگر درست نیست ویرایشش کنید.
            </p>
          )}
          {(tr.state === "unavailable" || tr.state === "failed") && (
            <div className="gf-msg bad" role="alert" data-testid="gf-tr-unavailable">
              <div>{tr.message || "ترجمهٔ خودکار انجام نشد."}</div>
              {tr.state === "unavailable" && (
                <div className="gf-tr-hint">
                  انگلیسی را همین‌جا در کادرِ بالا بنویسید؛ یا بی‌نوشتن «اجرا» را بزنید تا کار گم نشود و در صف بماند و به‌محضِ آماده‌شدنِ مترجم (روشن‌شدنِ
                  سرورِ پردازش یا شارژِ متیس) خودکار ترجمه و ساخته شود.
                </div>
              )}
              <button type="button" className="gf-btn" onClick={() => setRetry((n) => n + 1)} disabled={busy}>
                ترجمهٔ دوباره
              </button>
            </div>
          )}
          {!enOk && (
            <p className="gf-msg bad" role="alert">
              ترجمه باید فقط حرفِ لاتین داشته باشد (بدونِ حرفِ فارسی).
            </p>
          )}
        </div>
      )}

      <div className="gf-actions">
        <button type="button" className="gf-btn primary" onClick={() => void run()} disabled={busy || disabled}>
          اجرا
        </button>
        <button type="button" className="gf-btn" onClick={cancel} disabled={!busy}>
          انصراف
        </button>
      </div>
      {note && (
        <p className="gf-msg" role="status">
          {note}
        </p>
      )}

      {phase === "preparing" && (
        <div className="gf-progress" role="status">
          <Spinner size={16} />
          <span>در حالِ آماده‌کردنِ تصویر…</span>
        </div>
      )}
      {phase === "running" && (
        <div className={`gf-progress${waiting || holding ? " is-waiting" : ""}`} role="status" aria-live="polite">
          <div className="gf-progress-line">
            <Spinner size={16} />
            <span className="gf-progress-text">{status?.message || "در حالِ ارسال…"}</span>
            <span className="gf-elapsed" aria-label="زمانِ گذشته">
              {fa(elapsed)} ثانیه
            </span>
          </div>
          {!waiting && !holding && (
            <div className="gf-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <i style={{ width: `${Math.max(4, pct)}%` }} />
            </div>
          )}
          {trs?.state === "ok" && trs.en && (
            <p className="gf-sub" data-testid="gf-sent-translation">
              ترجمه: <bdi dir="ltr">{trs.en}</bdi> — {transLabel(trs)}
            </p>
          )}
          {holding && (
            <div className="gf-wait" data-testid="gf-wait-english">
              <label className="gf-label" htmlFor="gf-wait-en">
                یا همین حالا انگلیسی بنویسید
              </label>
              <div className="gf-tr-row">
                <input
                  id="gf-wait-en"
                  dir="ltr"
                  className="gf-en"
                  type="text"
                  maxLength={500}
                  value={waitEn}
                  placeholder="e.g. blue sky with white clouds"
                  onChange={(e) => setWaitEn(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void sendWaitEnglish();
                  }}
                />
                <button type="button" className="gf-btn" onClick={() => void sendWaitEnglish()} disabled={!validEnglish(waitEn) || waitBusy}>
                  ارسال و ساختن
                </button>
              </div>
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
          انجام شد{done.seconds ? ` (${fa(Math.round(done.seconds))} ثانیه)` : ""}؛ لایهٔ «پرکردن هوشمند» به پروژه اضافه شد.
          {done.translation?.state === "ok" && done.translation.en && (
            <>
              {" "}
              ترجمه: <bdi dir="ltr">{done.translation.en}</bdi>.
            </>
          )}{" "}
          اگر نتیجه را نپسندیدید دوباره «اجرا» را بزنید تا نمونهٔ دیگری ساخته شود.
        </p>
      )}
    </div>
  );
}
