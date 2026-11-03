import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Adjust, Curve, imageDataFrom, process } from "./engine";
import { EditState, FULL, Rect, Spot, transformedSize } from "./model";

export type ToolId =
  | "hand" | "crop" | "straighten" | "heal" | "text" | "logo" | "watermark" | "background" | "square" | "upscale"
  | "denoise" | "sharpen";

export type ZoomCmd = { id: number; kind: "fit" | "100" | "in" | "out" } | null;

type Override = { url: string; w: number; h: number } | null;

const WORK = 1280;
const DRAFT = 560;

type Props = {
  /** عکسِ کاری (۱۶۰۰ پیکسلی یا خودِ PNG شفاف) و اندازهٔ اصلی */
  src: string;
  origW: number;
  origH: number;
  state: EditState;
  tool: ToolId;
  compare: "off" | "before" | "split";
  /** پیش‌نمایشِ دقیقِ سرور (برش، چرخش، متن، لوگو…): جای عکسِ کاری می‌نشیند و هندسه دیگر دوباره اعمال نمی‌شود */
  override: Override;
  aspect: number | null;
  spotR: number;
  zoomCmd: ZoomCmd;
  onCrop: (r: Rect, commit: boolean) => void;
  onSpots: (s: Spot[]) => void;
  onZoom: (pct: number) => void;
  onStatus: (s: string) => void;
};

type Handle = "move" | "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se";

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("عکس بارگذاری نشد."));
    img.src = url;
  });
}

/** بومِ ادیتور: زوم و جابه‌جایی، پیش‌نمایشِ زندهٔ تنظیم‌ها، برش، ترمیم، قبل/بعد. */
export default function Viewport(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [box, setBox] = useState({ w: 800, h: 520 });
  const [view, setView] = useState<{ s: number | null; x: number; y: number }>({ s: null, x: 0, y: 0 });
  const [split, setSplit] = useState(0.5);
  const [ready, setReady] = useState(0);
  const base = useRef<{ full: ImageData; draft: ImageData; w: number; h: number } | null>(null);
  const adjCanvas = useRef<HTMLCanvasElement | null>(null);
  const baseCanvas = useRef<HTMLCanvasElement | null>(null);
  const buffers = useRef<{ full?: ImageData; draft?: ImageData }>({});
  const [adjVersion, setAdjVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const spaceDown = useRef(false);
  const drag = useRef<null | { kind: "pan" | "crop" | "split"; handle?: Handle; sx: number; sy: number; vx: number; vy: number; rect?: Rect }>(null);

  const imgUrl = p.override?.url ?? p.src;
  const Wo = p.override?.w ?? p.origW;
  const Ho = p.override?.h ?? p.origH;

  // ------------------------------------------------------------ بارگذاریِ عکس
  useEffect(() => {
    let stop = false;
    setLoadError(null);
    loadImage(imgUrl)
      .then((img) => {
        if (stop) return;
        const full = imageDataFrom(img, img.naturalWidth, img.naturalHeight, WORK);
        const draft = imageDataFrom(img, img.naturalWidth, img.naturalHeight, DRAFT);
        base.current = { full, draft, w: img.naturalWidth, h: img.naturalHeight };
        buffers.current = {};
        const bc = document.createElement("canvas");
        bc.width = full.width;
        bc.height = full.height;
        bc.getContext("2d")!.putImageData(full, 0, 0);
        baseCanvas.current = bc;
        setReady((v) => v + 1);
      })
      .catch((e) => !stop && setLoadError((e as Error).message));
    return () => {
      stop = true;
    };
  }, [imgUrl]);

  // ------------------------------------------------------------ اندازهٔ ظرف
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // ------------------------------------------------------------ پردازشِ تنظیم‌ها (پیش‌نویس سپس کامل)
  const adjust = p.state.adjust as Adjust;
  const curve = p.state.curve as Curve;
  const adjKey = useMemo(() => JSON.stringify([adjust, curve]), [adjust, curve]);
  useEffect(() => {
    const b = base.current;
    if (!b) return;
    if (!adjCanvas.current) adjCanvas.current = document.createElement("canvas");
    const put = (img: ImageData) => {
      const c = adjCanvas.current!;
      if (c.width !== img.width || c.height !== img.height) {
        c.width = img.width;
        c.height = img.height;
      }
      c.getContext("2d")!.putImageData(img, 0, 0);
      setAdjVersion((v) => v + 1);
    };
    const t0 = performance.now();
    buffers.current.draft = process(b.draft, adjust, curve, buffers.current.draft, true);
    put(buffers.current.draft);
    const draftMs = performance.now() - t0;
    const timer = window.setTimeout(() => {
      const t1 = performance.now();
      buffers.current.full = process(b.full, adjust, curve, buffers.current.full, false);
      put(buffers.current.full);
      p.onStatus(`پیش‌نمایش ${Math.round(performance.now() - t1)} میلی‌ثانیه (پیش‌نویس ${Math.round(draftMs)})`);
    }, 140);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adjKey, ready]);

  // ------------------------------------------------------------ هندسه
  const geoNeutral = p.override !== null || p.tool === "heal";
  const geo = geoNeutral ? { turn: 0 as const, straighten: 0, flipH: false, flipV: false, crop: FULL } : p.state;
  const [Wt, Ht] = transformedSize(Wo, Ho, geo);
  const showFull = p.tool === "crop" || p.tool === "straighten" || p.tool === "heal" || geoNeutral;
  const crop = showFull ? FULL : geo.crop;
  const frame = { x0: crop.x * Wt, y0: crop.y * Ht, w: crop.w * Wt, h: crop.h * Ht };
  const fitS = Math.min((box.w * 0.94) / frame.w, (box.h * 0.94) / frame.h);
  const s = view.s ?? fitS;
  const sRef = useRef(s);
  sRef.current = s;

  useEffect(() => {
    if (!p.zoomCmd) return;
    const k = p.zoomCmd.kind;
    if (k === "fit") setView({ s: null, x: 0, y: 0 });
    else if (k === "100") setView((v) => ({ ...v, s: Math.max(0.05, 1) }));
    else setView((v) => ({ ...v, s: Math.max(fitS * 0.4, Math.min(8, (v.s ?? fitS) * (k === "in" ? 1.25 : 0.8))) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.zoomCmd?.id]);

  useEffect(() => {
    p.onZoom(Math.round(s * 100));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.round(s * 100)]);

  const cx = box.w / 2 + view.x;
  const cy = box.h / 2 + view.y;
  const fcx = frame.x0 + frame.w / 2;
  const fcy = frame.y0 + frame.h / 2;
  const toScreen = useCallback((ux: number, uy: number): [number, number] => [cx + s * (ux - fcx), cy + s * (uy - fcy)], [cx, cy, s, fcx, fcy]);
  const toUnit = (sx: number, sy: number): [number, number] => [(sx - cx) / s + fcx, (sy - cy) / s + fcy];

  // ------------------------------------------------------------ کشیدن روی بوم
  useEffect(() => {
    const cv = canvas.current;
    const src = (p.compare === "before" ? baseCanvas.current : adjCanvas.current) ?? baseCanvas.current;
    if (!cv || !src) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(box.w * dpr) || cv.height !== Math.round(box.h * dpr)) {
      cv.width = Math.round(box.w * dpr);
      cv.height = Math.round(box.h * dpr);
    }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingQuality = "high";

    const paint = (image: CanvasImageSource, iw: number, ih: number, clipRight?: number) => {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(s, s);
      ctx.translate(-fcx, -fcy);
      // در «تمام عکس» همهٔ تصویرِ چرخیده دیده می‌شود؛ وگرنه فقط قابِ برش
      ctx.beginPath();
      ctx.rect(frame.x0, frame.y0, frame.w, frame.h);
      ctx.clip();
      if (clipRight !== undefined) {
        ctx.beginPath();
        ctx.rect(frame.x0, frame.y0, frame.w * clipRight, frame.h);
        ctx.clip();
      }
      ctx.translate(Wt / 2, Ht / 2);
      ctx.scale(geo.flipH ? -1 : 1, geo.flipV ? -1 : 1);
      ctx.rotate((-geo.straighten * Math.PI) / 180);
      ctx.rotate((-geo.turn * Math.PI) / 180);
      ctx.scale(Wo / iw, Ho / ih);
      ctx.translate(-iw / 2, -ih / 2);
      ctx.drawImage(image, 0, 0);
      ctx.restore();
    };
    paint(src, src.width, src.height);
    if (p.compare === "split" && baseCanvas.current && adjCanvas.current) {
      // «قبل» سمتِ چپِ خطِ جداکننده
      paint(baseCanvas.current, baseCanvas.current.width, baseCanvas.current.height, split);
      const [sx0, sy0] = toScreen(frame.x0 + frame.w * split, frame.y0);
      const [, sy1] = toScreen(frame.x0, frame.y0 + frame.h);
      ctx.fillStyle = "#fff";
      ctx.fillRect(sx0 - 1, sy0, 2, sy1 - sy0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adjVersion, ready, box, s, view.x, view.y, p.compare, split, Wt, Ht, crop.x, crop.y, crop.w, crop.h,
    geo.turn, geo.straighten, geo.flipH, geo.flipV, Wo, Ho, imgUrl]);

  // ------------------------------------------------------------ ورودی‌ها
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement)) {
        spaceDown.current = true;
        if (wrap.current) wrap.current.style.cursor = "grab";
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        spaceDown.current = false;
        if (wrap.current) wrap.current.style.cursor = "";
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const local = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = wrap.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  const onWheel = (e: React.WheelEvent) => {
    const [mx, my] = local(e);
    const old = sRef.current;
    const next = Math.max(fitS * 0.4, Math.min(8, old * Math.exp(-e.deltaY * 0.0015)));
    setView((v) => {
      const k = 1 - next / old;
      return { s: next, x: v.x + (mx - (box.w / 2 + v.x)) * k, y: v.y + (my - (box.h / 2 + v.y)) * k };
    });
  };

  const cropRectScreen = (() => {
    const [x0, y0] = toScreen(p.state.crop.x * Wt, p.state.crop.y * Ht);
    const [x1, y1] = toScreen((p.state.crop.x + p.state.crop.w) * Wt, (p.state.crop.y + p.state.crop.h) * Ht);
    return { x0, y0, x1, y1 };
  })();

  const beginCrop = (e: React.PointerEvent, handle: Handle) => {
    e.stopPropagation();
    const [sx, sy] = local(e);
    drag.current = { kind: "crop", handle, sx, sy, vx: 0, vy: 0, rect: { ...p.state.crop } };
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const [sx, sy] = local(e);
    if (p.compare === "split" && Math.abs(toScreen(frame.x0 + frame.w * split, 0)[0] - sx) < 14) {
      drag.current = { kind: "split", sx, sy, vx: 0, vy: 0 };
      (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
      return;
    }
    const panning = p.tool === "hand" || spaceDown.current || e.button === 1;
    if (panning) {
      drag.current = { kind: "pan", sx, sy, vx: view.x, vy: view.y };
      (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
      return;
    }
    if (p.tool === "heal" && e.button === 0) {
      const [ux, uy] = toUnit(sx, sy);
      if (ux < 0 || uy < 0 || ux > Wt || uy > Ht) return;
      const rx = ux / Wt;
      const ry = uy / Ht;
      const hit = p.state.spots.findIndex((sp) => Math.hypot((sp.x - rx) * Wt, (sp.y - ry) * Ht) < sp.r * Math.min(Wt, Ht) * 1.1);
      if (hit >= 0 || e.altKey) {
        if (hit >= 0) p.onSpots(p.state.spots.filter((_, i) => i !== hit));
        return;
      }
      p.onSpots([...p.state.spots, { x: +rx.toFixed(4), y: +ry.toFixed(4), r: p.spotR }]);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const [sx, sy] = local(e);
    if (d.kind === "pan") {
      setView((v) => ({ s: v.s ?? fitS, x: d.vx + (sx - d.sx), y: d.vy + (sy - d.sy) }));
    } else if (d.kind === "split") {
      const [ux] = toUnit(sx, sy);
      setSplit(Math.max(0.02, Math.min(0.98, (ux - frame.x0) / frame.w)));
    } else if (d.kind === "crop" && d.rect && d.handle) {
      const dx = (sx - d.sx) / s / Wt;
      const dy = (sy - d.sy) / s / Ht;
      p.onCrop(nextCrop(d.rect, d.handle, dx, dy, p.aspect, Wt, Ht), false);
    }
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.kind === "crop") p.onCrop(p.state.crop, true);
  };

  const spots = p.state.spots;
  const cropMode = p.tool === "crop";
  const gridLines = p.tool === "straighten";

  return (
    <div
      ref={wrap}
      className="vp-wrap"
      data-testid="viewport"
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onContextMenu={(e) => e.preventDefault()}
      style={{ cursor: p.tool === "hand" ? "grab" : p.tool === "heal" ? "crosshair" : undefined, touchAction: "none" }}
    >
      <canvas ref={canvas} className="vp-canvas" style={{ width: box.w, height: box.h }} data-testid="photo-canvas" />
      {loadError && <div className="vp-msg">{loadError}</div>}
      {!base.current && !loadError && <div className="vp-msg">در حالِ بارگذاری…</div>}

      {gridLines &&
        Array.from({ length: 9 }, (_, i) => {
          const [gx0, gy0] = toScreen(0, 0);
          const [gx1, gy1] = toScreen(Wt, Ht);
          const f = (i + 1) / 10;
          return (
            <span key={i}>
              <i className="vp-grid-v" style={{ left: gx0 + (gx1 - gx0) * f, top: gy0, height: gy1 - gy0 }} />
              <i className="vp-grid-h" style={{ top: gy0 + (gy1 - gy0) * f, left: gx0, width: gx1 - gx0 }} />
            </span>
          );
        })}

      {cropMode && (
        <div className="vp-crop" data-testid="crop-overlay">
          <i className="vp-shade" style={{ left: 0, top: 0, width: box.w, height: Math.max(0, cropRectScreen.y0) }} />
          <i className="vp-shade" style={{ left: 0, top: cropRectScreen.y1, width: box.w, height: Math.max(0, box.h - cropRectScreen.y1) }} />
          <i className="vp-shade" style={{ left: 0, top: cropRectScreen.y0, width: Math.max(0, cropRectScreen.x0), height: cropRectScreen.y1 - cropRectScreen.y0 }} />
          <i className="vp-shade" style={{ left: cropRectScreen.x1, top: cropRectScreen.y0, width: Math.max(0, box.w - cropRectScreen.x1), height: cropRectScreen.y1 - cropRectScreen.y0 }} />
          <div
            className="vp-crop-box"
            style={{ left: cropRectScreen.x0, top: cropRectScreen.y0, width: cropRectScreen.x1 - cropRectScreen.x0, height: cropRectScreen.y1 - cropRectScreen.y0 }}
            onPointerDown={(e) => beginCrop(e, "move")}
          >
            <i className="third-v" style={{ left: "33.33%" }} />
            <i className="third-v" style={{ left: "66.66%" }} />
            <i className="third-h" style={{ top: "33.33%" }} />
            <i className="third-h" style={{ top: "66.66%" }} />
            {(["nw", "n", "ne", "e", "se", "s", "sw", "w"] as Handle[]).map((h) => (
              <b
                key={h}
                className={`vp-handle h-${h}`}
                data-handle={h}
                onPointerDown={(e) => beginCrop(e, h)}
              />
            ))}
          </div>
        </div>
      )}

      {p.tool === "heal" &&
        spots.map((sp, i) => {
          const [sx, sy] = toScreen(sp.x * Wt, sp.y * Ht);
          const d = sp.r * Math.min(Wt, Ht) * 2 * s;
          return <i key={i} className="vp-spot" data-spot={i} style={{ left: sx - d / 2, top: sy - d / 2, width: d, height: d }} />;
        })}
    </div>
  );
}

/** حرکتِ یک دستگیره ⇐ مستطیلِ تازه (به نسبتِ تصویرِ چرخیده)، با قفلِ نسبت اگر خواسته شده */
export function nextCrop(start: Rect, h: Handle, dx: number, dy: number, ratio: number | null, Wt: number, Ht: number): Rect {
  const MIN = 0.03;
  if (h === "move") {
    return {
      ...start,
      x: Math.max(0, Math.min(1 - start.w, start.x + dx)),
      y: Math.max(0, Math.min(1 - start.h, start.y + dy)),
    };
  }
  let l = start.x;
  let t = start.y;
  let r = start.x + start.w;
  let b = start.y + start.h;
  if (h.includes("w")) l = Math.max(0, Math.min(r - MIN, l + dx));
  if (h.includes("e")) r = Math.min(1, Math.max(l + MIN, r + dx));
  if (h.includes("n")) t = Math.max(0, Math.min(b - MIN, t + dy));
  if (h.includes("s")) b = Math.min(1, Math.max(t + MIN, b + dy));
  if (ratio && ratio > 0) {
    // نسبتِ پیکسلی: (w·Wt)/(h·Ht) = ratio
    let w = r - l;
    let hh = b - t;
    const wantH = (w * Wt) / ratio / Ht;
    const wantW = (hh * Ht * ratio) / Wt;
    const horizontal = h === "e" || h === "w";
    const vertical = h === "n" || h === "s";
    if (vertical) {
      w = wantW;
      const mid = (l + r) / 2;
      l = mid - w / 2;
      r = mid + w / 2;
    } else if (horizontal) {
      hh = wantH;
      const mid = (t + b) / 2;
      t = mid - hh / 2;
      b = mid + hh / 2;
    } else {
      // گوشه: ضلعِ بزرگ‌تر را نگه دار، دیگری را بساز و از گوشهٔ مقابل لنگر بگیر
      if (wantH <= hh) hh = wantH;
      else w = wantW;
      if (h.includes("w")) l = r - w;
      else r = l + w;
      if (h.includes("n")) t = b - hh;
      else b = t + hh;
    }
    // داخل عکس نگه دار
    if (l < 0) { r -= l; l = 0; }
    if (t < 0) { b -= t; t = 0; }
    if (r > 1) { l -= r - 1; r = 1; }
    if (b > 1) { t -= b - 1; b = 1; }
    l = Math.max(0, l);
    t = Math.max(0, t);
    const maxW = r - l;
    const maxH = b - t;
    const scale = Math.min(1, maxW / Math.max(1e-6, w), maxH / Math.max(1e-6, hh));
    if (scale < 1) {
      const nw = w * scale;
      const nh = hh * scale;
      if (h.includes("w")) l = r - nw;
      else r = l + nw;
      if (h.includes("n")) t = b - nh;
      else b = t + nh;
    }
  }
  return { x: Math.max(0, l), y: Math.max(0, t), w: Math.max(MIN, Math.min(1, r) - Math.max(0, l)), h: Math.max(MIN, Math.min(1, b) - Math.max(0, t)) };
}
