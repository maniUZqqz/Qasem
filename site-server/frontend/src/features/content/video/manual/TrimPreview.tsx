import { RefObject, useEffect, useRef } from "react";

import type { MediaItem } from "../api";

/** یک فریم از یک منبع: ثانیهٔ «منبع» (نه تایم‌لاین) */
export type FrameAt = { ref: string; t: number };

/** آدرسِ قابلِ خواندن برای فریم: نسخهٔ سبک اگر آماده است؛ صدا، رسانهٔ توکن‌دار، شکل و توالیِ تودرتو ⇒ null (بی‌صدا نمایش داده نمی‌شود) */
export function frameSource(item: MediaItem | undefined, ref: string): { url: string; image: boolean } | null {
  if (!item || item.auth || item.kind === "audio") return null;
  if (ref === "shape" || ref.startsWith("seq:")) return null;
  if (item.kind === "image") return item.url ? { url: item.url, image: true } : null;
  const url = item.proxy === "ready" && item.proxy_url ? item.proxy_url : item.url;
  return url ? { url, image: false } : null;
}

type Want = { key: string; url: string; image: boolean; t: number };
type Slot = { busy: boolean; want: Want | null; done: string; alive: boolean };

// چند <video>ِ پنهان که بین کشیدن‌ها نگه داشته می‌شوند تا هر بار از نو بارگیری نشوند (حداکثر ۴ تا)
const pool = new Map<string, HTMLVideoElement>();
const images = new Map<string, HTMLImageElement>();

function videoFor(slot: string, url: string): HTMLVideoElement {
  const key = `${slot}|${url}`;
  const hit = pool.get(key);
  if (hit) {
    pool.delete(key);
    pool.set(key, hit);
    return hit;
  }
  const v = document.createElement("video");
  v.muted = true;
  v.playsInline = true;
  v.preload = "metadata";
  v.setAttribute("aria-hidden", "true");
  v.style.cssText = "position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
  v.src = url;
  document.body.appendChild(v);
  pool.set(key, v);
  while (pool.size > 4) {
    for (const [k, old] of pool) {
      pool.delete(k);
      old.removeAttribute("src");
      old.load();
      old.remove();
      break;
    }
  }
  return v;
}

/** منتظرِ یک رویداد می‌ماند؛ خطا یا کندی ⇒ reject (بی‌صدا گرفته می‌شود) */
function once(el: HTMLMediaElement, ev: string, ms: number): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    let timer = 0;
    const off = () => {
      window.clearTimeout(timer);
      el.removeEventListener(ev, onOk);
      el.removeEventListener("error", onErr);
    };
    const onOk = () => {
      off();
      resolve();
    };
    const onErr = () => {
      off();
      reject(new Error(ev));
    };
    timer = window.setTimeout(onErr, ms);
    el.addEventListener(ev, onOk);
    el.addEventListener("error", onErr);
  });
}

function draw(cv: HTMLCanvasElement | null, src: CanvasImageSource, sw: number, sh: number) {
  if (!cv || !sw || !sh) return;
  const k = 240 / Math.max(sw, sh);
  const W = Math.max(2, Math.round(sw * k));
  const H = Math.max(2, Math.round(sh * k));
  if (cv.width !== W || cv.height !== H) {
    cv.width = W;
    cv.height = H;
  }
  const x = cv.getContext("2d");
  if (!x) return;
  x.drawImage(src, 0, 0, W, H);
  cv.dataset.ready = "1";
}

async function grab(slot: string, want: Want, cv: HTMLCanvasElement | null): Promise<void> {
  if (want.image) {
    let img = images.get(want.url);
    if (!img) {
      img = new Image();
      img.src = want.url;
      images.set(want.url, img);
      if (images.size > 12) images.delete(images.keys().next().value as string);
    }
    if (!img.complete) await new Promise<void>((res, rej) => { img!.onload = () => res(); img!.onerror = () => rej(new Error("img")); });
    draw(cv, img, img.naturalWidth, img.naturalHeight);
    return;
  }
  const v = videoFor(slot, want.url);
  if (v.readyState < 1) await once(v, "loadedmetadata", 8000);
  const dur = v.duration;
  const t = Math.max(0, Number.isFinite(dur) && dur > 0 ? Math.min(want.t, dur - 0.02) : want.t);
  if (!(v.readyState >= 2 && Math.abs(v.currentTime - t) < 0.001)) {
    const done = once(v, "seeked", 3000);
    v.currentTime = t;
    await done;
  }
  draw(cv, v, v.videoWidth, v.videoHeight);
}

/** حلقهٔ پیش‌نمایش: همیشه حداکثر یک seek در جریان است و فقط آخرین درخواست اجرا می‌شود */
async function pump(slot: string, s: Slot, cv: RefObject<HTMLCanvasElement | null>) {
  if (s.busy) return;
  s.busy = true;
  try {
    while (s.alive && s.want && s.want.key !== s.done) {
      const w = s.want;
      try {
        await grab(slot, w, cv.current);
      } catch {
        /* فریم در دسترس نبود: بی‌صدا */
      }
      s.done = w.key;
      await new Promise<void>((r) => window.setTimeout(r, 40));
    }
  } finally {
    s.busy = false;
  }
}

function useFrame(at: FrameAt | null, media: Record<string, MediaItem>, cv: RefObject<HTMLCanvasElement | null>, slot: string) {
  const src = at ? frameSource(media[at.ref], at.ref) : null;
  const key = at && src ? `${src.url}|${src.image ? 0 : at.t.toFixed(3)}` : "";
  const st = useRef<Slot>({ busy: false, want: null, done: "", alive: true });
  useEffect(() => {
    const s = st.current;
    s.alive = true;
    return () => {
      s.alive = false;
    };
  }, []);
  useEffect(() => {
    const s = st.current;
    if (!at || !src) {
      s.want = null;
      return;
    }
    s.want = { key, url: src.url, image: src.image, t: at.t };
    void pump(slot, s, cv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return !!src;
}

/**
 * پیش‌نمایشِ برش: هنگامِ کشیدنِ لبهٔ یک قطعه، دو تصویرِ کوچک بالای تایم‌لاین می‌آید —
 * آخرین فریمِ سمتِ چپِ برش (خروجی) و اولین فریمِ سمتِ راست (ورودی). فریم‌ها از <video>ِ پنهان در زمانِ دقیقِ منبع خوانده می‌شوند.
 */
export default function TrimPreview({ out, inn, media, x, top }: { out: FrameAt | null; inn: FrameAt | null; media: Record<string, MediaItem>; x: number; top: number }) {
  const cvOut = useRef<HTMLCanvasElement>(null);
  const cvIn = useRef<HTMLCanvasElement>(null);
  const okOut = useFrame(out, media, cvOut, "out");
  const okIn = useFrame(inn, media, cvIn, "in");
  if (!out && !inn) return null;
  const W = typeof window === "undefined" ? 800 : window.innerWidth;
  const H = typeof window === "undefined" ? 600 : window.innerHeight;
  const left = Math.max(8, Math.min(W - 312, x - 152));
  const pos = top > 150 ? { bottom: H - top + 8 } : { top: 8 };
  return (
    <div className="tp-wrap" data-testid="trim-preview" dir="ltr" style={{ left, ...pos }}>
      <figure className="tp-slot">
        <div className="tp-box">
          <canvas ref={cvOut} className="tp-cv" width={2} height={2} />
          {!okOut && <em>{out ? "بدونِ تصویر" : "—"}</em>}
        </div>
        <figcaption dir="rtl">پیش از برش</figcaption>
      </figure>
      <i className="tp-cut" aria-hidden="true" />
      <figure className="tp-slot">
        <div className="tp-box">
          <canvas ref={cvIn} className="tp-cv" width={2} height={2} />
          {!okIn && <em>{inn ? "بدونِ تصویر" : "—"}</em>}
        </div>
        <figcaption dir="rtl">پس از برش</figcaption>
      </figure>
    </div>
  );
}
