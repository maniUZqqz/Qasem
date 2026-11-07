/**
 * آپلودِ تکه‌تکه و ادامه‌پذیر (برای اینترنتِ کند یا قطع‌وصل): فایل به تکه‌های کوچک بریده و فرستاده می‌شود؛ هر تکه که نرسید دوباره می‌رود، اینترنت که قطع شد
 * منتظر می‌ماند و وقتی وصل شد خودکار ادامه می‌دهد، و اگر صفحه بسته شود همان فایل را دوباره انتخاب کنید از همان‌جا ادامه می‌دهد.
 * سمتِ سرور: backend/apps/content/views_upload.py.  منطقِ این فایل بدونِ React و با «ترابری»ِ جایگزین‌پذیر است تا بی‌مرورگر آزموده شود.
 */
export type UploadPhase = "starting" | "uploading" | "retrying" | "offline" | "finishing" | "done" | "error" | "cancelled";

export type UploadState = {
  phase: UploadPhase;
  sent: number;
  total: number;
  /** بایت بر ثانیه (میانگینِ نرم) */
  speed: number;
  etaSec: number | null;
  /** شمارهٔ تلاشِ فعلیِ همین تکه (۱ = بدونِ مشکل) */
  attempt: number;
  maxAttempts: number;
  /** جملهٔ فارسی برای نمایش */
  message: string;
  /** اگر از جایی ادامه داده شد: درصدِ شروع */
  resumedFrom: number | null;
  /** خطای نهایی: دوباره امتحان با همان فایل پیشرفت را نگه می‌دارد */
  fatal: boolean;
};

export type StartReply = { upload_id: string; received: number; chunk: number; chunk_max: number; resumed?: boolean };
export type FinishReply<V = unknown> = { video: V; job_id: number | null };

export class HttpFail extends Error {
  constructor(public status: number, message: string, public code = "", public received?: number) {
    super(message);
  }
}

export type Transport<V = unknown> = {
  start: (body: { name: string; size: number; key: string; title: string }) => Promise<StartReply>;
  chunk: (uid: string, offset: number, blob: Blob, signal: AbortSignal, onBytes: (n: number) => void) => Promise<{ received: number }>;
  status: (uid: string) => Promise<{ received: number }>;
  finish: (uid: string) => Promise<FinishReply<V>>;
  cancel: (uid: string) => Promise<void>;
};

export type Env = {
  sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  online: () => boolean;
  /** تا وقتی اینترنت وصل شود یا لغو شود صبر می‌کند */
  waitOnline: (signal: AbortSignal) => Promise<void>;
  now: () => number;
};

export const MAX_ATTEMPTS = 10;
export const MIN_CHUNK = 256 * 1024;
const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];

export class UploadCancelled extends Error {
  constructor() {
    super("آپلود لغو شد.");
  }
}
export class UploadFailed extends Error {
  constructor(message: string, public code: string, public fatal = true) {
    super(message);
  }
}

export const fileKey = (f: { name: string; size: number; lastModified?: number }) => `${f.name}:${f.size}:${f.lastModified ?? 0}`;

/** جملهٔ فارسی برای یک خطای HTTP یا شبکه */
export function describeFailure(err: unknown): { retry: boolean; message: string; code: string } {
  if (err instanceof HttpFail) {
    const s = err.status;
    if (s === 0) return { retry: true, message: "اینترنت قطع یا بسیار ضعیف است.", code: "network" };
    if ([408, 425, 429, 500, 502, 503, 504].includes(s)) return { retry: true, message: "سرور لحظه‌ای جواب نداد.", code: `http${s}` };
    if (s === 413) return { retry: true, message: "تکهٔ فرستاده‌شده برای مسیرِ اینترنت بزرگ بود؛ کوچک‌ترش می‌کنم.", code: "chunk_too_big" };
    return { retry: false, message: err.message || "خطا در آپلود.", code: err.code || `http${s}` };
  }
  return { retry: true, message: "اینترنت قطع یا بسیار ضعیف است.", code: "network" };
}

/** رقم‌های فارسی (و «٫» برای اعشار) — بدونِ وابستگی به React تا در آزمون هم کار کند */
export const faDigits = (x: string | number) => String(x).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]).replace(/\./g, "٫");
export const fmtBytes = (n: number) => (n >= 1048576 ? `${faDigits((n / 1048576).toFixed(n >= 104857600 ? 0 : 1))} مگابایت` : `${faDigits(Math.max(1, Math.round(n / 1024)))} کیلوبایت`);
export function fmtEta(sec: number | null): string {
  if (sec === null || !isFinite(sec)) return "";
  if (sec < 5) return "چند ثانیه";
  if (sec < 90) return `${faDigits(Math.round(sec))} ثانیه`;
  if (sec < 5400) return `${faDigits(Math.round(sec / 60))} دقیقه`;
  return `${faDigits((sec / 3600).toFixed(1))} ساعت`;
}

export type RunOptions<V> = {
  transport: Transport<V>;
  env: Env;
  signal: AbortSignal;
  onState: (s: UploadState) => void;
  title?: string;
};

/** بدنهٔ اصلی: یک فایل را کامل می‌فرستد؛ در موفقیت جوابِ finish را می‌دهد، وگرنه UploadFailed / UploadCancelled. */
export async function runUpload<V>(file: Blob & { name: string; lastModified?: number }, opt: RunOptions<V>): Promise<FinishReply<V>> {
  const { transport, env, signal } = opt;
  const total = file.size;
  const st: UploadState = { phase: "starting", sent: 0, total, speed: 0, etaSec: null, attempt: 1, maxAttempts: MAX_ATTEMPTS, message: "در حالِ آماده‌سازی…", resumedFrom: null, fatal: false };
  const emit = (patch: Partial<UploadState>) => {
    Object.assign(st, patch);
    st.etaSec = st.speed > 1 && st.phase !== "done" ? Math.max(0, (total - st.sent) / st.speed) : null;
    opt.onState({ ...st });
  };
  const check = () => {
    if (signal.aborted) throw new UploadCancelled();
  };

  let session: StartReply | null = null;
  const startSession = async () => {
    for (let i = 0; ; i++) {
      check();
      try {
        return await transport.start({ name: file.name, size: total, key: fileKey(file), title: opt.title ?? file.name });
      } catch (e) {
        const d = describeFailure(e);
        if (!d.retry || i >= 4) throw new UploadFailed(d.retry ? "به سرور وصل نشد؛ اینترنت را بررسی کنید و دوباره امتحان کنید." : d.message, d.code);
        if (!env.online()) await env.waitOnline(signal);
        else await env.sleep(BACKOFF_MS[Math.min(i, BACKOFF_MS.length - 1)], signal);
      }
    }
  };

  session = await startSession();
  let offset = Math.min(session.received, total);
  if (session.resumed && offset > 0) emit({ resumedFrom: Math.round((offset / total) * 100), message: `از ${faDigits(Math.round((offset / total) * 100))}٪ ادامه می‌دهم…` });
  emit({ phase: "uploading", sent: offset });
  let size = Math.max(MIN_CHUNK, Math.min(session.chunk || 2097152, session.chunk_max || 8388608));
  const maxSize = session.chunk_max || 8388608;
  let restarted = false;

  while (offset < total) {
    check();
    let attempt = 0;
    for (;;) {
      check();
      if (!env.online()) {
        emit({ phase: "offline", message: "اینترنت قطع است؛ وقتی وصل شد خودکار ادامه می‌دهم. (پیشرفت نگه داشته شده)" });
        await env.waitOnline(signal);
        emit({ phase: "uploading", attempt: 1, message: "" });
      }
      const end = Math.min(total, offset + size);          // recomputed on every pass: a failed piece is re-sent SMALLER
      const blob = file.slice(offset, end);
      attempt++;
      const t0 = env.now();
      try {
        const r = await transport.chunk(session!.upload_id, offset, blob, signal, (n) => emit({ sent: offset + Math.min(n, end - offset), phase: "uploading" }));
        const dt = Math.max(1, env.now() - t0);
        const inst = ((end - offset) / dt) * 1000;
        emit({ speed: st.speed ? st.speed * 0.6 + inst * 0.4 : inst });
        offset = Math.max(end, Math.min(total, r.received));
        emit({ sent: offset, phase: "uploading", attempt: 1, message: "" });
        if (dt < 2500 && size < maxSize) size = Math.min(maxSize, Math.round(size * 1.5));
        else if (dt > 12000 && size > MIN_CHUNK) size = Math.max(MIN_CHUNK, Math.round(size / 2));
        break;
      } catch (e) {
        if (signal.aborted) throw new UploadCancelled();
        if (e instanceof HttpFail && e.status === 409 && e.code !== "overflow" && typeof e.received === "number") {
          offset = Math.min(total, e.received);                                  // the server knows better where we are
          emit({ sent: offset });
          break;
        }
        if (e instanceof HttpFail && e.status === 404 && !restarted) {           // the session was swept: begin again, the file is still here
          restarted = true;
          emit({ phase: "starting", message: "آپلودِ قبلی منقضی شده بود؛ از اول می‌فرستم…", sent: 0, resumedFrom: null });
          session = await startSession();
          offset = Math.min(session.received, total);
          break;
        }
        const d = describeFailure(e);
        if (!d.retry) throw new UploadFailed(d.message, d.code);
        size = Math.max(MIN_CHUNK, Math.round(size / (d.code === "chunk_too_big" ? 4 : 2)));
        if (attempt >= MAX_ATTEMPTS) {
          throw new UploadFailed("چند بار تلاش کردم ولی تکه به سرور نرسید. پیشرفتِ شما نگه داشته شده؛ وقتی اینترنت بهتر شد همین فایل را دوباره انتخاب کنید تا از همین‌جا ادامه یابد.", "gave_up");
        }
        if (!env.online()) continue;                                              // the top of the loop waits for the line
        emit({ phase: "retrying", attempt: attempt + 1, message: `${d.message} تلاشِ دوباره (${faDigits(attempt + 1)} از ${faDigits(MAX_ATTEMPTS)})…` });
        await env.sleep(BACKOFF_MS[Math.min(attempt - 1, BACKOFF_MS.length - 1)], signal);
        // the piece may have landed although the answer was lost: ask before sending it again
        try {
          const s2 = await transport.status(session!.upload_id);
          if (s2.received >= end) {
            offset = Math.min(total, s2.received);
            emit({ sent: offset });
            break;
          }
          offset = Math.max(offset, Math.min(total, s2.received));
        } catch { /* the next send decides */ }
      }
    }
  }
  check();
  emit({ phase: "finishing", sent: total, message: "در حالِ بررسیِ فایل…" });
  for (let i = 0; ; i++) {
    try {
      const done = await transport.finish(session!.upload_id);
      emit({ phase: "done", sent: total, message: "آپلود کامل شد." });
      return done;
    } catch (e) {
      const d = describeFailure(e);
      if (e instanceof HttpFail && e.status === 409 && typeof e.received === "number" && e.received < total) {
        return runUpload(file, opt);                                             // the server lost pieces: go round again (it resumes)
      }
      if (!d.retry || i >= 4) throw new UploadFailed(d.retry ? "آپلود کامل شد ولی بررسیِ نهایی جواب نداد؛ دوباره امتحان کنید (از همین‌جا ادامه می‌یابد)." : d.message, d.code);
      if (!env.online()) await env.waitOnline(signal);
      else await env.sleep(BACKOFF_MS[Math.min(i, BACKOFF_MS.length - 1)], signal);
    }
  }
}
