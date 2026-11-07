import type { MediaItem } from "../api";

/** آدرسِ مناسبِ خواندنِ فریم: نسخهٔ سبک اگر هست (آمارِ رنگ به پیکسلِ دقیق نیاز ندارد) */
export const frameUrl = (item: MediaItem): string => (item.proxy === "ready" && item.proxy_url ? item.proxy_url : item.url);

/**
 * یک فریمِ کوچک (ضلعِ بلند ≤ maxSide) از یک ویدیو یا عکس در لحظهٔ `t` (ثانیهٔ خودِ فایل). برای آمارِ رنگ (رنگِ خودکار و تطبیقِ رنگ).
 * خطا = Error با پیامِ فارسی.
 */
export function grabFrame(item: MediaItem, t: number, maxSide = 256): Promise<ImageData> {
  return new Promise((resolve, reject) => {
    const url = frameUrl(item);
    const fail = (msg: string) => reject(new Error(msg));
    const draw = (w: number, h: number, src: CanvasImageSource) => {
      const k = Math.min(1, maxSide / Math.max(w, h));
      const cw = Math.max(2, Math.round(w * k));
      const ch = Math.max(2, Math.round(h * k));
      const c = document.createElement("canvas");
      c.width = cw;
      c.height = ch;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return fail("مرورگر اجازهٔ خواندنِ تصویر را نداد.");
      ctx.drawImage(src, 0, 0, cw, ch);
      try {
        resolve(ctx.getImageData(0, 0, cw, ch));
      } catch {
        fail("خواندنِ فریم ممکن نشد (دسترسیِ مرورگر).");
      }
    };
    if (item.kind === "image") {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => draw(img.naturalWidth, img.naturalHeight, img);
      img.onerror = () => fail("عکس باز نشد.");
      img.src = url;
      return;
    }
    const v = document.createElement("video");
    v.muted = true;
    v.playsInline = true;
    v.preload = "auto";
    v.crossOrigin = "anonymous";
    const timer = window.setTimeout(() => { cleanup(); fail("خواندنِ فریم از فیلم بیش از ۲۰ ثانیه طول کشید؛ فیلم را ببینید که پخش می‌شود یا «پیش‌نمایشِ سبک» بسازید."); }, 20000);
    const cleanup = () => {
      window.clearTimeout(timer);
      v.removeAttribute("src");
      v.load();
    };
    v.onerror = () => { cleanup(); fail("این فیلم در مرورگر باز نشد؛ برایش «پیش‌نمایشِ سبک» بسازید."); };
    v.onloadedmetadata = () => {
      const at = Math.max(0, Math.min((v.duration || 1) - 0.05, t));
      v.onseeked = () => {
        cleanup();
        draw(v.videoWidth || 320, v.videoHeight || 180, v);
      };
      v.currentTime = at;
    };
    v.src = url;
  });
}
