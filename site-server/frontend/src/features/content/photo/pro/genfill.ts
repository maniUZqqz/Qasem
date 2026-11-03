import { api } from "../../../../api/client";
import type { GenFillResult, GenFillStart, GenFillStatus } from "../api";

/**
 * کلاینتِ «پرکردنِ هوشمند» (FLUX inpaint روی سرورِ پردازش).
 *
 *   POST   stores/<id>/photo-editor/genfill/          multipart {image, mask, asset, prompt?, seed?}
 *   GET    stores/<id>/photo-editor/genfill/<job>/    وضعیت؛ READY ⇒ {asset, layer:{cx,cy,w}}
 *   DELETE stores/<id>/photo-editor/genfill/<job>/    لغو
 *
 * هیچ وابستگی‌ای به Stage / ProWorkspace ندارد؛ تصویر و ماسک را خودِ فراخواننده می‌دهد.
 */

const url = (store: string, job = "") => `/stores/${store}/photo-editor/genfill/${job ? `${job}/` : ""}`;

export type GenFillArgs = {
  /** عکسِ کتابخانه‌ای که پروژه به آن تعلق دارد */
  assetId: number;
  /** PNG ِ بومِ فعلی (ترکیبِ لایه‌ها)، حداکثر ۲۰۴۸ پیکسل */
  image: Blob;
  /** PNG ِ خاکستری هم‌اندازهٔ image؛ سفید = جایی که باید پر شود */
  mask: Blob;
  /** خالی = حذفِ شیء و پر کردن با پس‌زمینه */
  prompt?: string;
  seed?: number;
};

export class GenFillError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GenFillError";
  }
}

export const isAbort = (err: unknown): boolean =>
  (err instanceof DOMException && err.name === "AbortError") ||
  (typeof err === "object" && err !== null && ((err as { code?: string }).code === "ERR_CANCELED" || (err as { name?: string }).name === "CanceledError"));

const abortError = () => new DOMException("لغو شد", "AbortError");

export function startGenFill(store: string, a: GenFillArgs, signal?: AbortSignal): Promise<GenFillStart> {
  const body = new FormData();
  body.append("image", a.image, "image.png");
  body.append("mask", a.mask, "mask.png");
  body.append("asset", String(a.assetId));
  body.append("prompt", a.prompt ?? "");
  if (a.seed !== undefined) body.append("seed", String(a.seed));
  return api.post<GenFillStart>(url(store), body, { signal }).then((r) => r.data);
}

export const genFillStatus = (store: string, job: string, signal?: AbortSignal): Promise<GenFillStatus> =>
  api.get<GenFillStatus>(url(store, job), { signal }).then((r) => r.data);

/** لغوِ بی‌خطا (اگر کار نبود/تمام شده بود ساکت می‌ماند) */
export const cancelGenFill = (store: string, job: string): Promise<void> =>
  api.delete(url(store, job)).then(
    () => undefined,
    () => undefined,
  );

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(abortError());
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export type RunOptions = {
  /** با AbortController لغو می‌شود؛ کارِ سمتِ سرور هم لغو می‌شود (مگر keepJobOnAbort) */
  signal?: AbortSignal;
  /** هر بار که وضعیتی رسید (شروعِ کار هم یک بار) */
  onUpdate?: (s: GenFillStatus) => void;
  /** کارِ ثبت‌شده را دوباره بگیر به‌جای شروعِ تازه (پس از بازکردنِ دوبارهٔ صفحه) */
  resumeJob?: string;
  /** وقتی شناسهٔ کار معلوم شد */
  onJob?: (job: string) => void;
  /** با abort کارِ سمتِ سرور را لغو نکن (میزبان شناسه را نگه می‌دارد و بعداً resume می‌کند) */
  keepJobOnAbort?: boolean;
  /** فاصلهٔ پرسیدن (میلی‌ثانیه)، به‌تدریج تا ۴ ثانیه بیشتر می‌شود */
  intervalMs?: number;
};

/**
 * شروع + پرسیدنِ مکرر تا تمام شدن. READY ⇒ نتیجه؛ FAILED/CANCELLED ⇒ GenFillError (پیامِ فارسیِ سرور)؛
 * abort ⇒ DOMException("AbortError"). خطای گذرای شبکه در پرسیدن تا سه بار تحمل می‌شود.
 */
export async function runGenFill(store: string, a: GenFillArgs, opts: RunOptions = {}): Promise<GenFillResult> {
  const { signal, onUpdate, onJob } = opts;
  let job = opts.resumeJob ?? "";
  if (!job) {
    const start = await startGenFill(store, a, signal);
    job = start.job;
    onJob?.(job);
    onUpdate?.({ job, state: start.state, message: start.message, progress: 0, node: null, online: start.online });
  } else {
    onJob?.(job);
  }
  let wait = Math.max(300, opts.intervalMs ?? 1500);
  let failures = 0;
  for (;;) {
    try {
      await sleep(wait, signal);
    } catch (err) {
      if (!opts.keepJobOnAbort) void cancelGenFill(store, job);
      throw err;
    }
    let st: GenFillStatus;
    try {
      st = await genFillStatus(store, job, signal);
      failures = 0;
    } catch (err) {
      if (isAbort(err)) {
        if (!opts.keepJobOnAbort) void cancelGenFill(store, job);
        throw abortError();
      }
      const code = (err as { response?: { status?: number } }).response?.status;
      if (code === 404) throw new GenFillError("این کار پیدا نشد (شاید لغو یا پاک شده است).");
      if (++failures >= 3) throw err;
      continue;
    }
    onUpdate?.(st);
    if (st.state === "READY") {
      if (!st.asset || !st.layer) throw new GenFillError("نتیجه ناقص برگشت؛ دوباره امتحان کنید.");
      return st as GenFillResult;
    }
    if (st.state === "FAILED") throw new GenFillError(st.error || "پرکردنِ هوشمند انجام نشد.");
    if (st.state === "CANCELLED") throw new GenFillError("پرکردنِ هوشمند لغو شد.");
    wait = Math.min(4000, Math.round(wait * 1.15));
  }
}
