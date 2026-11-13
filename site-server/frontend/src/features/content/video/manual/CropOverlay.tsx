import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { countRender } from "../../../../hooks/perfCount";
import type { MediaItem } from "../api";
import AutoReframe from "./AutoReframe";
import { Num } from "./controls";
import { keyNear, removeKey, valueAt } from "./keyframes";
import { MediaClip, Reframe, clipEnd } from "./model";
import {
  ASPECTS, AspectKey, Handle, Rect, aspectRatio, centredWindow, detectAspect, dragWindow, hasReframeKeys, lockK, rectToReframe, reframeCenter,
  reframeWindow, setCenterKey, withNumeric, withoutKeys, clampRect,
} from "./reframe";

/**
 * «برشِ قاب» روی مانیتورِ برنامه: کلِ منبعِ قطعه (contain) با بخشِ بیرون از پنجره تیره، پنجره با ۸ دستگیره و کشیدنِ بدنه (جابه‌جایی).
 * مختصاتِ پنجره «کسری از منبع» است (همان Reframe ِ مدل). هنگامِ کشیدن `onReframe(..., false)` (زنده) و هنگامِ رها شدن
 * `onReframe(..., true)` (یک گامِ برگشتِ «برشِ قاب») صدا زده می‌شود.
 */
export type CropSource = HTMLVideoElement | HTMLImageElement;

/** پدر: reframe ِ تازه (undefined = بدونِ برش)؛ `extra` برای تغییرِ هم‌زمانِ ویژگی‌های دیگرِ قطعه (مثلاً fit) */
export type OnReframe = (id: string, reframe: Reframe | undefined, final: boolean, extra?: Partial<MediaClip>) => void;

/**
 * اندازهٔ واقعیِ منبع [عرض, ارتفاع]. اگر element آماده است همان (چیزی که واقعاً کشیده می‌شود، با چرخشِ فراداده)،
 * وگرنه اندازهٔ ثبت‌شدهٔ رسانه در بسته.
 */
export function sourceSize(item: MediaItem | undefined, el: CropSource | null): [number, number] | null {
  if (el instanceof HTMLVideoElement && el.videoWidth > 0 && el.videoHeight > 0) return [el.videoWidth, el.videoHeight];
  if (el instanceof HTMLImageElement && el.naturalWidth > 0 && el.naturalHeight > 0) return [el.naturalWidth, el.naturalHeight];
  if (item?.width && item?.height) return [item.width, item.height];
  return null;
}

const PAD = 14;
const HANDLES: Handle[] = ["tl", "tr", "bl", "br", "t", "b", "l", "r"];
const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

type Drag = { handle: Handle; px0: number; py0: number; r0: Rect; c0: MediaClip; rel: number; last: Reframe | undefined; moved: boolean };

type OverlayProps = {
  clip: MediaClip;
  /** زمانِ سرِ پخش (تایم‌لاین) */
  time: number;
  playing: boolean;
  frameW: number;
  frameH: number;
  dims: [number, number] | null;
  el: CropSource | null;
  /** با هر بار بومِ برنامه تازه شد بالا می‌رود (دوباره‌کشیدنِ منبع) */
  version: number;
  aspect: AspectKey;
  frameAspect: number;
  onReframe: OnReframe;
  onSeekClip: () => void;
  onClose: () => void;
  /** مانیتور هر بار که یک فریمِ پخش را کشید خبر می‌دهد؛ با آن، در حالِ پخش بومِ برش با همان فریم تازه می‌شود (حلقهٔ rAFِ جداگانه نمی‌خواهد). نیامد ⇒ همان حلقهٔ قدیمی */
  subscribeFrame?: (fn: () => void) => () => void;
};

export function CropOverlay({ clip, time, playing, frameW, frameH, dims, el, version, aspect, frameAspect, onReframe, onSeekClip, onClose, subscribeFrame }: OverlayProps) {
  const layer = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const win = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [loaded, setLoaded] = useState(false);
  const inside = time >= clip.at - 0.001 && time <= clipEnd(clip) + 0.001;
  const sa = dims ? dims[0] / dims[1] : 0;
  const lock = lockK(aspectRatio(aspect, frameAspect), sa);

  /** جایگاهِ منبع (contain) داخلِ قاب، با حاشیه‌ای که دستگیره‌های لبه بیرون نزنند */
  const geo = useMemo(() => {
    if (!(sa > 0)) return null;
    const aw = Math.max(24, frameW - 2 * PAD);
    const ah = Math.max(24, frameH - 2 * PAD);
    const dw = aw / ah > sa ? ah * sa : aw;
    return { x: (frameW - dw) / 2, y: (frameH - dw / sa) / 2, w: dw, h: dw / sa };
  }, [sa, frameW, frameH]);

  const paint = useCallback((): boolean => {
    const c = cv.current;
    if (!c || !geo) return false;
    countRender("cropPaint");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = Math.max(2, Math.round(frameW * dpr));
    const H = Math.max(2, Math.round(frameH * dpr));
    if (c.width !== W || c.height !== H) {
      c.width = W;
      c.height = H;
    }
    const g = c.getContext("2d");
    if (!g) return false;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#000";
    g.fillRect(0, 0, W, H);
    const ok = !!el && (el instanceof HTMLVideoElement ? el.readyState >= 2 && el.videoWidth > 0 : el.complete && el.naturalWidth > 0);
    if (ok && el) g.drawImage(el, geo.x * dpr, geo.y * dpr, geo.w * dpr, geo.h * dpr);
    return ok;
  }, [el, geo, frameW, frameH]);

  // منبع را با هر تغییرِ زمان/فریم دوباره بکش (ایستاده: رویداد‌محور؛ در حالِ پخش: حلقهٔ rAF)
  useEffect(() => {
    const ok = paint();
    setLoaded((p) => (p === ok ? p : ok));
  }, [paint, version, time]);
  useEffect(() => {
    if (!el) return undefined;
    const again = () => {
      const ok = paint();
      setLoaded((p) => (p === ok ? p : ok));
    };
    const evs = ["seeked", "loadeddata", "canplay", "load"];
    evs.forEach((ev) => el.addEventListener(ev, again));
    return () => evs.forEach((ev) => el.removeEventListener(ev, again));
  }, [el, paint]);
  useEffect(() => {
    if (!playing) return undefined;
    // ۱۴۰۵/۰۸/۲۳: مانیتور خودش هر فریم را می‌کشد؛ همان‌جا خبر می‌گیریم (یک حلقهٔ rAF کمتر که هر فریم دوباره روی بوم می‌کشید)
    if (subscribeFrame) return subscribeFrame(() => { paint(); });
    let raf = 0;
    const loop = () => {
      paint();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, paint, subscribeFrame]);

  const ready = !!geo && inside;
  useEffect(() => {
    if (ready) win.current?.focus({ preventScroll: true });
  }, [ready, clip.id]);

  // ───────── هندسهٔ پنجره (کسری از منبع ⇒ پیکسلِ قاب)
  const r = reframeWindow(clip, time, 1, 1);
  const rf = clip.reframe;
  const path = useMemo(() => {
    if (!geo || !rf || !hasReframeKeys(rf)) return [];
    const ts = Array.from(new Set([...(rf.kx ?? []), ...(rf.ky ?? [])].map((k) => k.t))).sort((a, b) => a - b);
    return ts.map((t) => ({ t, x: geo.x + valueAt(rf.kx, t, rf.cx) * geo.w, y: geo.y + valueAt(rf.ky, t, rf.cy) * geo.h }));
  }, [geo, rf]);

  const toFrac = (e: { clientX: number; clientY: number }): [number, number] | null => {
    const box = layer.current?.getBoundingClientRect();
    if (!box || !geo || !box.width || !box.height) return null;
    const x = (e.clientX - box.left) * (frameW / box.width);
    const y = (e.clientY - box.top) * (frameH / box.height);
    return [(x - geo.x) / geo.w, (y - geo.y) / geo.h];
  };

  const begin = (e: React.PointerEvent<HTMLElement>, handle: Handle) => {
    if (!ready) return;
    e.stopPropagation();
    e.preventDefault();
    const p = toFrac(e);
    if (!p) return;
    drag.current = { handle, px0: p[0], py0: p[1], r0: reframeWindow(clip, time, 1, 1), c0: clip, rel: time - clip.at, last: clip.reframe, moved: false };
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* مرورگرهای قدیمی */
    }
    win.current?.focus({ preventScroll: true });
  };
  const move = (e: React.PointerEvent) => {
    const st = drag.current;
    if (!st) return;
    const p = toFrac(e);
    if (!p) return;
    const next = rectToReframe(dragWindow(st.r0, st.handle, p[0] - st.px0, p[1] - st.py0, lock), st.c0.reframe, st.rel);
    st.last = next;
    st.moved = true;
    onReframe(st.c0.id, next, false);
  };
  const end = () => {
    const st = drag.current;
    if (!st) return;
    drag.current = null;
    if (st.moved) onReframe(st.c0.id, st.last, true);
  };

  // ───────── صفحه‌کلید: فلش = ۱ پیکسلِ منبع (Shift = ۱۰)
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    const d = ARROWS[e.key];
    if (!d) return;
    e.preventDefault();
    e.stopPropagation();
    if (!dims) return;
    const step = e.shiftKey ? 10 : 1;
    const cur = reframeWindow(clip, time, 1, 1);
    onReframe(clip.id, rectToReframe(clampRect({ ...cur, x: cur.x + (d[0] * step) / dims[0], y: cur.y + (d[1] * step) / dims[1] }), clip.reframe, time - clip.at), false);
  };
  const onKeyUp = (e: React.KeyboardEvent) => {
    if (ARROWS[e.key] && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.stopPropagation();
      onReframe(clip.id, clip.reframe, true);
    }
  };

  const px = dims ? `${fa(Math.round(r.w * dims[0]))}×${fa(Math.round(r.h * dims[1]))}` : "";

  return (
    <div ref={layer} className="cr-layer" dir="ltr" data-testid="crop-overlay" onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <canvas ref={cv} className="cr-canvas" />
      {!geo && <div className="cr-msg" dir="rtl">در حالِ خواندنِ اندازهٔ تصویرِ منبع…</div>}
      {geo && !loaded && inside && <div className="cr-msg" dir="rtl">در حالِ بارگیریِ تصویرِ منبع…</div>}
      {!inside && (
        <div className="cr-msg" dir="rtl" data-testid="crop-outside">
          سرِ پخش بیرونِ این قطعه است.
          <button type="button" className="ws-btn" onClick={onSeekClip}>رفتن به ابتدای قطعه</button>
        </div>
      )}
      {ready && geo && (
        <>
          {path.length > 0 && (
            <svg className="cr-path" width={frameW} height={frameH} viewBox={`0 0 ${frameW} ${frameH}`} aria-hidden data-testid="crop-path">
              {path.length > 1 && <polyline points={path.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")} />}
              {path.map((p) => <circle key={p.t} cx={p.x} cy={p.y} r={3.5} className={Math.abs(p.t - (time - clip.at)) <= 0.04 ? "is-here" : ""} />)}
            </svg>
          )}
          <div
            ref={win} className={`cr-win ${lock ? "is-locked" : ""}`} tabIndex={0} role="group" aria-label="پنجرهٔ برش؛ با فلش‌ها جابه‌جا کنید"
            style={{ left: geo.x + r.x * geo.w, top: geo.y + r.y * geo.h, width: r.w * geo.w, height: r.h * geo.h }}
            onPointerDown={(e) => begin(e, "body")} onKeyDown={onKeyDown} onKeyUp={onKeyUp} data-testid="crop-window"
          >
            <i className="cr-dot" />
            {HANDLES.map((h) => (
              <i key={h} className={`cr-h ${h}`} data-testid={`crop-handle-${h}`} data-handle={h} onPointerDown={(e) => begin(e, h)} />
            ))}
          </div>
          {px && <div className="cr-badge" dir="ltr">{px}</div>}
        </>
      )}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════ پنلِ زیرِ مانیتور
type PanelProps = {
  storeId?: string;
  clip: MediaClip;
  time: number;
  dims: [number, number] | null;
  aspect: AspectKey;
  frameAspect: number;
  onAspect: (k: AspectKey) => void;
  onReframe: OnReframe;
  onClose: () => void;
};

const FIELDS: { k: "l" | "t" | "w" | "h"; label: string; title: string }[] = [
  { k: "l", label: "چپ ٪", title: "فاصلهٔ لبهٔ چپِ پنجره از لبهٔ چپِ منبع" },
  { k: "t", label: "بالا ٪", title: "فاصلهٔ لبهٔ بالای پنجره از لبهٔ بالای منبع" },
  { k: "w", label: "پهنا ٪", title: "پهنای پنجره نسبت به پهنای منبع" },
  { k: "h", label: "ارتفاع ٪", title: "ارتفاعِ پنجره نسبت به ارتفاعِ منبع" },
];

export function CropPanel({ storeId, clip, time, dims, aspect, frameAspect, onAspect, onReframe, onClose }: PanelProps) {
  const sa = dims ? dims[0] / dims[1] : 0;
  const lock = lockK(aspectRatio(aspect, frameAspect), sa);
  const rel = time - clip.at;
  const cur = reframeWindow(clip, time, 1, 1);
  const rf = clip.reframe;
  const keys = hasReframeKeys(rf);
  const keyCount = Math.max(rf?.kx?.length ?? 0, rf?.ky?.length ?? 0);
  const here = !!rf && (!!keyNear(rf.kx, rel) || !!keyNear(rf.ky, rel));
  const dirty = useRef(false);
  const inside = time >= clip.at - 0.001 && time <= clipEnd(clip) + 0.001;

  const pick = (k: AspectKey) => {
    onAspect(k);
    const ratio = aspectRatio(k, frameAspect);
    if (!ratio || !(sa > 0)) return;
    onReframe(clip.id, centredWindow(ratio, sa, clip.reframe), true);
  };

  const editNum = (f: "l" | "t" | "w" | "h", pct: number) => {
    if (!Number.isFinite(pct)) return;
    dirty.current = true;
    onReframe(clip.id, rectToReframe(withNumeric(cur, f, pct / 100, lock), clip.reframe, rel), false);
  };
  const commitNum = () => {
    if (!dirty.current) return;
    dirty.current = false;
    onReframe(clip.id, clip.reframe, true);
  };

  /** ◆ کلیدِ موقعیتِ پنجره در سرِ پخش (دوباره زدن همان‌جا کلید را برمی‌دارد) */
  const toggleKey = () => {
    if (!rf || !inside) return;
    const [cx, cy] = reframeCenter(clip, time);
    if (here) {
      const kx = removeKey(rf.kx, rel);
      const ky = removeKey(rf.ky, rel);
      const next: Reframe = { w: rf.w, h: rf.h, cx: kx.length ? rf.cx : Math.round(cx * 10000) / 10000, cy: ky.length ? rf.cy : Math.round(cy * 10000) / 10000 };
      if (kx.length) next.kx = kx;
      if (ky.length) next.ky = ky;
      onReframe(clip.id, next, true);
    } else {
      onReframe(clip.id, { ...rf, kx: setCenterKey(rf.kx, rel, cx), ky: setCenterKey(rf.ky, rel, cy) }, true);
    }
  };

  return (
    <div className="cr-panel" dir="rtl" data-testid="crop-panel"
      onKeyDown={(e) => { if ((e.key === "Delete" || e.key === "Backspace") && !(e.target instanceof HTMLInputElement)) e.stopPropagation(); }}>
      <div className="cr-head">
        <b>برشِ قاب</b>
        <span className="ws-hint">پنجره را بکشید؛ از گوشه‌ها و لبه‌ها اندازه‌اش را عوض کنید. فلش‌ها ۱ پیکسل (با Shift ۱۰) جابه‌جا می‌کنند. کیفیت از فایلِ اصلی می‌آید.</span>
      </div>

      <div className="cr-chips" role="group" aria-label="نسبتِ پنجره">
        {ASPECTS.map((a) => (
          <button key={a.key} type="button" className={`ws-chip ${aspect === a.key ? "is-on" : ""}`} aria-pressed={aspect === a.key} onClick={() => pick(a.key)} data-testid={`crop-aspect-${a.key}`}
            title={a.key === "free" ? "پنجره هر نسبتی داشته باشد" : a.key === "frame" ? "هم‌نسبتِ قابِ پروژه" : `پنجره همیشه ${a.title} می‌ماند`}>
            {a.title}
          </button>
        ))}
      </div>

      <div className="cr-nums">
        {FIELDS.map((f) => (
          <div key={f.k} data-testid={`crop-num-${f.k}`} title={f.title} onBlur={commitNum} onKeyDown={(e) => { if (e.key === "Enter") commitNum(); }}>
            <Num label={f.label} step={1} min={0} max={100} value={Math.round((f.k === "l" ? cur.x : f.k === "t" ? cur.y : f.k === "w" ? cur.w : cur.h) * 1000) / 10} onChange={(v) => editNum(f.k, v)} />
          </div>
        ))}
      </div>

      <div className="cr-btns">
        <button type="button" className={`ws-btn ${here ? "is-on" : ""}`} onClick={toggleKey} disabled={!rf || !inside} data-testid="crop-key"
          title={rf ? (here ? "کلیدِ موقعیتِ همین لحظه را بردار" : "موقعیتِ فعلیِ پنجره را در سرِ پخش کلید بزن؛ بین کلیدها پنجره نرم حرکت می‌کند") : "اول پنجره را کوچک‌تر کنید"}>
          {here ? "◆ برداشتنِ کلید" : "◆ کلیدِ موقعیت"}
        </button>
        {keys && (
          <button type="button" className="ws-btn" onClick={() => onReframe(clip.id, withoutKeys(clip, time), true)} data-testid="crop-clear-keys" title="همهٔ کلیدهای حرکتِ پنجره پاک شود؛ پنجره همین‌جا ثابت می‌ماند">
            حذفِ همهٔ کلیدها{keyCount ? ` (${fa(keyCount)})` : ""}
          </button>
        )}
        <button type="button" className="ws-btn" onClick={() => onReframe(clip.id, undefined, true)} disabled={!rf} data-testid="crop-reset" title="برش برداشته شود و کلِ تصویر دیده شود">بازنشانی</button>
        <button type="button" className="ws-btn" onClick={() => onReframe(clip.id, clip.reframe, true, { fit: "cover" })} disabled={clip.fit === "cover"} data-testid="crop-fill"
          title="تصویرِ بریده‌شده کادر را کامل پر کند (بدونِ نوارِ سیاه)">پُر کردنِ قاب</button>
        <span className="ws-spacer" />
        <button type="button" className="ws-btn primary" onClick={onClose} data-testid="crop-close" title="بستنِ حالتِ برش (Esc)">بستن</button>
      </div>
      {rf && clip.fit !== "cover" && <p className="ws-hint">اگر کنارِ تصویر نوارِ سیاه می‌بینید «پُر کردنِ قاب» را بزنید.</p>}
      {keys && <p className="ws-hint">پنجره در طولِ قطعه حرکت می‌کند: نقطه‌ها مسیرِ مرکزِ پنجره‌اند. پنجره را در هر لحظه بکشید تا کلیدِ همان لحظه عوض شود.</p>}

      <AutoReframe
        storeId={storeId} clip={clip} compact
        onApply={(next) => { onReframe(clip.id, next, true); if (sa > 0) onAspect(detectAspect(next, sa, frameAspect)); }}
      />
    </div>
  );
}
