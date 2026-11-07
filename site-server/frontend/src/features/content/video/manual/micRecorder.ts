/**
 * ضبط با میکروفونِ مرورگر برای «گویندگی». مرورگرها میکروفون را فقط روی نشانیِ امن (https یا localhost) می‌دهند؛
 * تا وقتی دامنه و https وصل نشده دکمه خاموش می‌ماند و دلیلش را می‌گوید.
 */

export const MIC_NEEDS_HTTPS = "ضبط با میکروفون: وقتی دامنه و https وصل شد فعال می‌شود. تا آن موقع صدا را با گوشی ضبط و آپلود کنید یا از متن بسازید.";
export const MIC_NO_BROWSER = "این مرورگر ضبط با میکروفون را پشتیبانی نمی‌کند؛ صدا را با گوشی ضبط و آپلود کنید یا از متن بسازید.";
export const MAX_RECORD_SECONDS = 300;

export type MicEnv = {
  isSecureContext?: boolean;
  navigator?: { mediaDevices?: { getUserMedia?: unknown } };
  MediaRecorder?: unknown;
};

export type MicSupport = { ok: boolean; reason: string };

/** آیا ضبط ممکن است؟ اگر نه، چرا (جملهٔ فارسی برای کاربر) */
export function micSupport(env: MicEnv = globalThis as unknown as MicEnv): MicSupport {
  if (!env.isSecureContext) return { ok: false, reason: MIC_NEEDS_HTTPS };
  if (!env.navigator?.mediaDevices?.getUserMedia || typeof env.MediaRecorder === "undefined") return { ok: false, reason: MIC_NO_BROWSER };
  return { ok: true, reason: "" };
}

const MIMES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];

/** اولین قالبِ صوتیِ پشتیبانی‌شده (کروم webm، سافاری mp4)؛ "" = بگذار مرورگر خودش انتخاب کند */
export function pickMime(isTypeSupported: (t: string) => boolean): string {
  return MIMES.find((m) => { try { return isTypeSupported(m); } catch { return false; } }) ?? "";
}

export function recordingFileName(mime: string, now = new Date()): string {
  const ext = /mp4/.test(mime) ? "m4a" : /ogg/.test(mime) ? "ogg" : "webm";
  const p = (n: number) => String(n).padStart(2, "0");
  return `voice-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.${ext}`;
}

/** پیامِ فارسی برای خطاهای getUserMedia */
export function micErrorText(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError") return "اجازهٔ میکروفون داده نشد. در تنظیماتِ مرورگر برای این سایت میکروفون را «مجاز» کنید و دوباره بزنید.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "میکروفونی پیدا نشد. یکی را وصل کنید یا صدا را با گوشی ضبط و آپلود کنید.";
  if (name === "NotReadableError" || name === "AbortError") return "میکروفون در دسترس نیست (شاید برنامهٔ دیگری از آن استفاده می‌کند).";
  return "ضبط شروع نشد؛ دوباره امتحان کنید یا صدا را آپلود کنید.";
}

export type Recorder = { stop: () => void; cancel: () => void };

/** شروعِ ضبط. `onDone` با فایلِ نهایی صدا زده می‌شود (یا null اگر چیزی ضبط نشد)؛ خودکار پس از MAX_RECORD_SECONDS می‌ایستد. */
export async function startRecording(onDone: (file: File | null) => void, onTick?: (seconds: number) => void): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const mime = pickMime((t) => MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks: Blob[] = [];
  let cancelled = false;
  const t0 = Date.now();
  const timer = window.setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    onTick?.(s);
    if (s >= MAX_RECORD_SECONDS && rec.state === "recording") rec.stop();
  }, 250);
  rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  rec.onstop = () => {
    window.clearInterval(timer);
    stream.getTracks().forEach((t) => t.stop());
    if (cancelled || !chunks.length) return onDone(null);
    const type = rec.mimeType || mime || "audio/webm";
    onDone(new File(chunks, recordingFileName(type), { type }));
  };
  rec.start(500);
  return {
    stop: () => { if (rec.state === "recording") rec.stop(); },
    cancel: () => { cancelled = true; if (rec.state === "recording") rec.stop(); else { window.clearInterval(timer); stream.getTracks().forEach((t) => t.stop()); } },
  };
}
