import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Asset } from "../api";
import { FULL, Rect } from "../manual/model";
import { nextCrop } from "../manual/Viewport";
import { FrameInput, FrameSpec, cropFormatOpParams, makeFrameSpec, normalizeCropFormat, normalizeView } from "./frame";
import { GEO_IDENTITY, Geo, GeoState, ViewState, mul } from "./geo";
import { ProEngine, WORK_MAX } from "./gl/engine";
import { maskLine } from "./gl/raster";
import type { LiquifyStore } from "./liquify";
import type { Hist } from "./panelTypes";
import { StrokeSession, selectionAlpha, type StrokeMode } from "./paint";
import type { PaintStore } from "./paint";
import { PEN_MAX, PenPath, penSvgD } from "./pen";
import { estimateEye } from "./redeye";
import { MaskStore, Selection, ToolId, ToolOpts, ZoomCmd, isSampleTool } from "./session";
import { canonical, descendantIds, effectivelyHidden, effectivelyLocked } from "./tree";
import {
  AdjustLayer, Layer, ProState, Pt2, Quad, RetouchLayer, Stroke, isPaintLayer, makeAdjust, makeRedeye, makeRetouch, makeText,
} from "./types";

export type StageApi = {
  engine: ProEngine;
  /** نمای فعلی: در حالتِ «بوم» بومِ نهایی (Wo/Ho = اندازهٔ واقعیِ بوم)، در حالتِ «عکس» (ابزارهای هندسه) خودِ عکس */
  geo: () => Geo | null;
  /** مشخصاتِ قابِ فعلی (اندازهٔ بومِ نهایی، H، …) */
  frame: () => FrameSpec | null;
  /** پنجرهٔ «سوژه (خودکار)» برای این حالت [x, y, w, h] — null اگر لازم نیست؛ هنگامِ ساخت به crop_format داده می‌شود */
  smartWindow: (s: ProState) => number[] | null;
  /** تصویرِ فضای عکس (مثلاً ماسکِ سوژه) ⇒ بومِ ۲بعدیِ فضای بومِ نهایی */
  warpToCanvas: (img: TexImageSource) => HTMLCanvasElement | null;
  redraw: () => void;
  layerSize: (l: Layer) => { w: number; h: number } | null;
  thumbnail: (adjust: Record<string, number>, curve: Record<string, [number, number][]>, size: number) => string | null;
  readFull: () => { data: Uint8ClampedArray; w: number; h: number } | null;
};

type Props = {
  src: string;
  origW: number;
  origH: number;
  /** عکسِ اصل شفاف است (برای «سوژه (خودکار)») */
  hasAlpha?: boolean;
  state: ProState;
  hist: Hist;
  tool: ToolId;
  opts: ToolOpts;
  setOpts: (p: Partial<ToolOpts>) => void;
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  masks: MaskStore;
  /** لایه‌های نقاشی (نوبت ۵) */
  paints: PaintStore;
  /** لایهٔ نقاشیِ فعال را برمی‌گرداند یا تازه می‌سازد */
  ensurePaint: () => { layerId: string; paintId: string } | null;
  onBucket: (nx: number, ny: number) => void;
  onPickColor: (nx: number, ny: number) => void;
  /** بومِ منبعِ قلمِ تاریخچه (هم‌اندازهٔ بوم) یا null */
  historySource: () => HTMLCanvasElement | null;
  /** نوکِ تصویریِ قلم‌موی دلخواه (یا null) */
  brushTip: () => HTMLCanvasElement | null;
  selection: Selection;
  assets: Asset[];
  storeLogo: string | null;
  compare: "off" | "before" | "split";
  exact: HTMLImageElement | null;
  zoomCmd: ZoomCmd;
  aspect: number | null;
  onZoom: (pct: number) => void;
  onStatus: (s: string) => void;
  onReady: (api: StageApi) => void;
  onHistogram: (h: { r: Uint32Array; g: Uint32Array; b: Uint32Array; l: Uint32Array; clipLo: number; clipHi: number }) => void;
  onSelectionChange: () => void;
  /** قلم (Pen): مسیرِ در حالِ ساخت (فضای بومِ نهایی) — هر تغییرِ آن ⇒ onPenChange تا نوارِ گزینه‌ها تازه شود */
  pen: PenPath;
  onPenChange: () => void;
  /** مایع‌سازی: نقشهٔ جابه‌جاییِ پروژه (فضای عکس) */
  liquify: LiquifyStore;
  onMaskEdited: (id: string) => void;
  onWb: (nx: number, ny: number) => void;
  onSubject: () => void;
  onNeedTextFocus: () => void;
  onToolChange: (t: ToolId) => void;
  onError: (msg: string) => void;
  onImageSizes?: () => void;
};

type Handle = "move" | "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se";
type Drag =
  | { k: "pan"; sx: number; sy: number; vx: number; vy: number }
  | { k: "split" }
  | { k: "crop"; handle: Handle; sx: number; sy: number; rect: Rect }
  | { k: "cropnew"; fx: number; fy: number }
  | { k: "move"; id: string; start: Pt2; c0: Pt2; moved: boolean }
  | { k: "photo"; start: Pt2; c0: Pt2; zoom: number; fw: number; fh: number; tw: number; th: number; moved: boolean }
  | { k: "gmove"; id: string; hitId: string; start: Pt2; orig: [string, Pt2][]; box: { x0: number; y0: number; x1: number; y1: number } | null; moved: boolean }
  | { k: "scale"; id: string; handle: string; d0: number; layer: Layer }
  | { k: "rotate"; id: string; a0: number; rot0: number }
  | { k: "paint"; id: string; last: [number, number]; white: boolean }
  | { k: "pt"; layerId: string; paintId: string; ss: StrokeSession; last: [number, number]; label: string }
  | { k: "grad"; id: string; p0: Pt2; kind: "linear" | "radial" }
  | { k: "gh"; id: string; which: "p0" | "p1" | "c" | "r" }
  | { k: "stroke"; id: string }
  | { k: "sel"; kind: "marquee" | "ellipse" | "lasso"; p0: Pt2; pts: Pt2[]; base: HTMLCanvasElement | null; mode: "new" | "add" | "sub" }
  | { k: "quad"; corner: keyof Quad }
  | { k: "pen"; kind: "new" | "anchor" | "ho" | "hi"; i: number; start: Pt2; orig: Pt2; sx: number; sy: number; moved: boolean; smooth: boolean }
  | { k: "liq"; last: Pt2; changed: boolean; t: number; timer: number }
  | { k: "gf"; last: Pt2; sub: boolean };

const SNAP_PX = 7;
const SEL_TOOLS = new Set<ToolId>(["marquee", "ellipse", "lasso", "subject", "genfill", "pen"]);
/** ابزارهایی که دایرهٔ اندازهٔ قلم زیرِ اشاره‌گر دارند */
const CURSOR_TOOLS = new Set<ToolId>(["brush", "clone", "heal", "liquify", "genfill", "redeye", "paint", "pencil", "eraser", "history", "blur", "sharpen", "smudge", "dodge", "burn", "sponge"]);
const CROSS_TOOLS = ["brush", "clone", "heal", "spot", "gradient", "marquee", "ellipse", "lasso", "wb", "subject", "text", "pen", "redeye", "liquify", "genfill", "paint", "pencil", "eraser", "bucket", "history", "picker", "blur", "sharpen", "smudge", "dodge", "burn", "sponge"];

const rad = (d: number) => (d * Math.PI) / 180;

/** مختصات لایه ⇐ ۴ گوشه در سندِ نرمال (۰..۱) */
function corners(l: Layer, size: { w: number; h: number }, Wo: number, Ho: number): Pt2[] {
  if (!("cx" in l)) return [];
  const r = rad("rot" in l ? l.rot : 0);
  const asp = Wo / Ho;
  const out: Pt2[] = [];
  for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const ox = (sx * size.w) / 2;
    const oy = (sy * size.h) / 2;
    const rx = ox * Math.cos(r) - oy * Math.sin(r);
    const ry = ox * Math.sin(r) + oy * Math.cos(r);
    out.push([l.cx + rx, l.cy + ry * asp]);
  }
  return out;
}

const lineIntersectionPoint = (p: Pt2, c: Pt2[]) => {
  // p داخلِ چهارضلعیِ محدبِ c؟
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const a = c[i];
    const b = c[(i + 1) % 4];
    const cr = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    if (cr !== 0) {
      if (sign === 0) sign = cr > 0 ? 1 : -1;
      else if ((cr > 0 ? 1 : -1) !== sign) return false;
    }
  }
  return true;
};

/** بخشی از حالت که قاب را می‌سازد */
export const frameInputOf = (s: ProState): FrameInput => ({
  turn: s.turn, straighten: s.straighten, flipH: s.flipH, flipV: s.flipV, crop: s.crop, persp: s.persp, tools: s.tools,
});

export default function Stage(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<ProEngine | null>(null);
  const [box, setBox] = useState({ w: 800, h: 520 });
  const [view, setView] = useState<ViewState>({ s: null, x: 0, y: 0 });
  const [split, setSplit] = useState(0.5);
  const [ready, setReady] = useState(0);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [glErr, setGlErr] = useState<string | null>(null);
  /** بافتِ WebGL از دست رفت (مثلاً ریستِ کارت گرافیک/فشارِ حافظه) ⇒ پیام روی بوم تا بازیابی؛ engineKey با هر بازیابی بالا می‌رود
   *  و موتور روی همان بوم از نو ساخته می‌شود (حالت: تاریخچه/لایه/ماسک/انتخاب/مایع‌سازی همه در React و CPU اند و می‌مانند) */
  const [engineKey, setEngineKey] = useState(0);
  const [glLost, setGlLost] = useState(false);
  const [glWaited, setGlWaited] = useState(false);
  /** «بازیابی»ِ دستی: عنصرِ canvas عوض می‌شود تا بافتِ WebGL تازه ساخته شود */
  const [canvasGen, setCanvasGen] = useState(0);
  const baseImg = useRef<{ src: string; img: HTMLImageElement } | null>(null);
  const [tick, setTick] = useState(0);
  const [guides, setGuides] = useState<{ x: number | null; y: number | null }>({ x: null, y: null });
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [cloneSrc, setCloneSrc] = useState<Pt2 | null>(null);
  const drag = useRef<Drag | null>(null);
  const spaceDown = useRef(false);
  const stateRef = useRef(p.state);
  stateRef.current = p.state;
  const propsRef = useRef(p);
  propsRef.current = p;
  const cloneRef = useRef<{ pending: Pt2 | null; offset: Pt2 | null }>({ pending: null, offset: null });
  const raf = useRef(0);
  const dirty = useRef({ render: true, present: true });
  const lastHist = useRef(0);
  const geoRef = useRef<Geo | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;

  // اندازهٔ عکسِ اصل. `Wo/Ho` ِ پایین‌تر (پس از geo) اندازهٔ «سندِ نما» است: بومِ نهایی یا (در حالتِ هندسه) خودِ عکس
  const PW = p.origW;
  const PH = p.origH;
  const specRef = useRef<FrameSpec | null>(null);
  const lastSpecKey = useRef<string | null>(null);

  // ───────────────────────── موتور
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    let eng: ProEngine | null = null;
    // از دست رفتنِ بافت: موتورِ فعلی بی‌اعتبار می‌شود؛ با «بازگشتِ بافت» (webglcontextrestored) engineKey بالا می‌رود و این افکت
    // موتورِ تازه می‌سازد. preventDefault شرطِ بازگشتِ بافت است. (شنونده‌ها پیش از ساختِ موتور ثبت می‌شوند تا بازگشت را هیچ‌وقت از دست ندهیم.)
    const onLost = (e: Event) => {
      e.preventDefault();
      if (eng) eng.ok = false;
      setGlLost(true);
    };
    const onRestored = () => setEngineKey((k) => k + 1);
    cv.addEventListener("webglcontextlost", onLost);
    cv.addEventListener("webglcontextrestored", onRestored);
    const teardown = () => {
      cv.removeEventListener("webglcontextlost", onLost);
      cv.removeEventListener("webglcontextrestored", onRestored);
      eng?.dispose();
      engineRef.current = null;
      cancelAnimationFrame(raf.current);
      raf.current = 0; // وگرنه (StrictMode ِ توسعه) schedule برای همیشه «در انتظار» می‌ماند
      if (drag.current?.k === "liq") window.clearInterval(drag.current.timer);
    };
    try {
      eng = new ProEngine(cv);
    } catch (e) {
      setGlLost(false); // پیامِ خطا (glErr) دیده شود
      setGlErr((e as Error).message);
      return teardown;
    }
    if (eng.g.lost) {
      // هنوز از دست‌رفته است (مثلاً «بازیابی»ِ دستی زود زده شد): منتظرِ webglcontextrestored می‌مانیم
      eng.ok = false;
      setGlLost(true);
      return teardown;
    }
    // (پیامِ «در حال بازیابی» تا گذاشتنِ عکسِ پایه روی موتورِ تازه می‌ماند؛ `ready` فقط بالا می‌رود تا افکت‌های وابسته به آن دوباره اجرا شوند)
    const eng0 = eng;
    setGlErr(null);
    engineRef.current = eng0;
    eng0.paintSrc = propsRef.current.paints.map;
    eng0.onNeedRender = () => {
      dirty.current.render = true;
      setTick((t) => t + 1);
    };
    // StageApi تازه (موتورِ تازه): ProWorkspace آن را در state و window.__photoPro می‌گذارد
    p.onReady({
      engine: eng0,
      geo: () => geoRef.current,
      frame: () => specRef.current,
      smartWindow: (s) => {
        const spec = makeFrameSpec(propsRef.current.origW, propsRef.current.origH, frameInputOf(s));
        return spec.smartPending ? eng0.smartWindow(spec) : null;
      },
      warpToCanvas: (img) => eng0.warpToCanvas(img),
      redraw: () => {
        dirty.current.render = true;
        dirty.current.present = true;
        schedule();
      },
      layerSize: (l) => eng0.layerSize(l),
      thumbnail: (a, c, size) => eng0.thumbnail(a, c, size),
      readFull: () => eng0.readFull(),
    });
    return teardown;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineKey]);

  // بافت از دست رفته و چند ثانیه گذشت ⇒ دکمهٔ «بازیابی» (اگر مرورگر خودش بازنگرداند)
  useEffect(() => {
    if (!glLost) return;
    const t = window.setTimeout(() => setGlWaited(true), 5000);
    return () => window.clearTimeout(t);
  }, [glLost, engineKey]);

  /** مرورگر بافت را خودش برنگرداند: بومِ تازه (⇒ بافتِ تازه) + موتورِ تازه؛ حالت همان می‌ماند */
  const retryGl = () => {
    setCanvasGen((g) => g + 1);
    setEngineKey((k) => k + 1);
  };

  const schedule = useCallback(() => {
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = 0;
      frame();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ───────────────────────── بارگذاریِ عکسِ پایه
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    let stop = false;
    setLoadErr(null);
    const apply = (img: HTMLImageElement) => {
      if (stop || !eng.ok) return; // بافت در این فاصله دوباره رفت ⇒ پس از بازگشت، افکت از نو اجرا می‌شود
      eng.setBase(img, PW, PH, WORK_MAX, !!p.hasAlpha);
      dirty.current.render = true;
      dirty.current.present = true;
      setReady((v) => v + 1);
      setGlLost(false);
      setGlWaited(false);
    };
    // بازیابیِ بافتِ GL: همان عکسِ بارگذاری‌شده دوباره به موتورِ تازه داده می‌شود (بی‌شبکه)
    const have = baseImg.current;
    if (have && have.src === p.src) {
      apply(have.img);
      return () => {
        stop = true;
      };
    }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (stop) return;
      baseImg.current = { src: p.src, img };
      apply(img);
    };
    img.onerror = () => !stop && setLoadErr("عکس بارگذاری نشد.");
    img.src = p.src;
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.src, glErr, engineKey]);

  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    eng.setExact(p.exact);
    dirty.current.render = true;
    schedule();
  }, [p.exact, ready, schedule]);

  // تصویرِ لایه‌ها
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    for (const l of p.state.layers) {
      if (l.type !== "image" || l.src.kind === "paint") continue;
      const key = l.src.kind === "logo" ? "logo" : `a${l.src.asset}`;
      const url = l.src.kind === "logo" ? p.storeLogo : (() => {
        const a = p.assets.find((x) => x.id === (l.src as { asset: number }).asset);
        return a ? (a.has_alpha ? a.url : a.preview || a.url) : null;
      })();
      if (url) void eng.ensureImage(key, url).then(() => propsRef.current.onImageSizes?.());
    }
  }, [p.state.layers, p.assets, p.storeLogo, ready]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: Math.max(50, el.clientWidth), h: Math.max(50, el.clientHeight) }));
    ro.observe(el);
    setBox({ w: Math.max(50, el.clientWidth), h: Math.max(50, el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  // ───────────────────────── هندسه
  // دو حالتِ نما: «بوم» (پیش‌فرض: بومِ نهایی با زوم/جابه‌جایی؛ لایه‌ها دیده و ویرایش می‌شوند) و «عکس» (ابزارِ برش/صاف/پرسپکتیو/
  // لکه فعال است: کلِ عکسِ بی‌برش با Geo(showFull)، لایه‌ها پنهان). جابه‌جاییِ حالت، نما را «جا شدن» می‌کند.
  const neutral = p.tool === "persp" || p.tool === "spot";
  const showFull = p.tool === "crop" || p.tool === "straighten" || neutral;
  const photoMode = showFull;
  const photoModeRef = useRef(photoMode);
  photoModeRef.current = photoMode;
  const gs: GeoState = neutral
    ? { turn: 0, straighten: 0, flipH: false, flipV: false, persp: null, crop: FULL }
    : { turn: p.state.turn, straighten: p.state.straighten, flipH: p.state.flipH, flipV: p.state.flipV, persp: p.state.persp, crop: p.state.crop };

  // مشخصاتِ قاب؛ «سوژه (خودکار)» با کَش (در حالتِ عکس فقط از کَش تا کشیدنِ دستگیره‌های برش گران نشود)
  const frameInput = useMemo(
    () => frameInputOf(p.state),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [p.state.turn, p.state.straighten, p.state.flipH, p.state.flipV, p.state.crop, p.state.persp, p.state.tools],
  );
  const spec = useMemo(() => {
    let sp = makeFrameSpec(PW, PH, frameInput);
    const e = engineRef.current;
    if (sp.smartPending && e && ready) {
      const w = e.smartWindow(sp, photoMode);
      if (w) sp = makeFrameSpec(PW, PH, frameInput, w);
    }
    return sp;
  }, [PW, PH, frameInput, ready, photoMode]);
  specRef.current = spec;

  const geo = useMemo(
    () => (photoMode
      ? new Geo(PW, PH, gs, true, box, view)
      : new Geo(spec.Wf, spec.Hf, GEO_IDENTITY, true, box, view)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [PW, PH, photoMode, spec.Wf, spec.Hf, gs.turn, gs.straighten, gs.flipH, gs.flipV, gs.persp, gs.crop.x, gs.crop.y, gs.crop.w, gs.crop.h, box, view],
  );
  geoRef.current = geo;
  const Wo = geo.Wo;
  const Ho = geo.Ho;

  // قاب عوض شد ⇒ موتور اندازهٔ بوم را می‌گیرد؛ ماسک‌ها/انتخابِ تازه به همان اندازه ساخته می‌شوند و انتخابِ قبلی (که به قابِ قدیم
  // تعلق داشت) پاک می‌شود
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng || !ready) return;
    eng.setFrame(spec);
    p.masks.setSize(eng.Wc, eng.Hc);
    p.paints.setSize(eng.Wc, eng.Hc);
    eng.paintSrc = p.paints.map;
    p.selection.setSize(eng.Wc, eng.Hc);
    if (lastSpecKey.current !== null && lastSpecKey.current !== spec.key && p.selection.active) {
      p.selection.clear();
      p.onSelectionChange();
    }
    if (lastSpecKey.current !== null && lastSpecKey.current !== spec.key && p.pen.active) {
      p.pen.clear(); // مسیرِ قلم هم به قابِ قدیم تعلق داشت
      p.onPenChange();
    }
    lastSpecKey.current = spec.key;
    dirty.current.render = true;
    dirty.current.present = true;
    schedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, ready]);

  useEffect(() => {
    setView({ s: null, x: 0, y: 0 });
    dirty.current.render = true;
    dirty.current.present = true;
    schedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoMode]);

  useEffect(() => {
    if (!p.zoomCmd) return;
    const k = p.zoomCmd.kind;
    const g = geoRef.current!;
    if (k === "fit") setView({ s: null, x: 0, y: 0 });
    else if (k === "100") setView((v) => ({ ...v, s: 1 }));
    else setView((v) => ({ ...v, s: Math.max(g.fitS * 0.3, Math.min(10, (v.s ?? g.fitS) * (k === "in" ? 1.25 : 0.8))) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.zoomCmd?.id]);

  useEffect(() => {
    p.onZoom(Math.round(geo.s * 100));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.round(geo.s * 100)]);

  // ───────────────────────── رندر و نمایش
  const frame = () => {
    const eng = engineRef.current;
    const cv = canvas.current;
    const g = geoRef.current;
    if (!eng || !cv || !g || !eng.ok) return;
    const pr = propsRef.current;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const bw = Math.round(boxRef.current.w * dpr);
    const bh = Math.round(boxRef.current.h * dpr);
    if (cv.width !== bw || cv.height !== bh) {
      cv.width = bw;
      cv.height = bh;
      dirty.current.present = true;
    }
    if (dirty.current.render) {
      dirty.current.render = false;
      const t0 = performance.now();
      try {
        // سوییچِ حالتِ نما: «عکس» (ابزارِ هندسه فعال ⇒ فقط مرحلهٔ ۱: کلِ عکسِ ظهورشده، لایه‌ها پنهان) یا «بوم»
        // (مرحلهٔ ۱ ⇒ ۲ قاب ⇒ ۳ لایه‌ها روی بومِ نهایی؛ نمایش = زوم/جابه‌جاییِ همان بوم). موتور: ProEngine.render / renderPhoto.
        const lq = pr.liquify;
        eng.setLiquify({ field: lq.field, gw: lq.gw, gh: lq.gh, ver: lq.ver, active: lq.active }); // مایع‌سازی: فضای عکس، پیش از قاب
        if (photoModeRef.current) eng.renderPhoto(stateRef.current);
        else eng.render(stateRef.current, { masks: pr.masks.map });
      } catch (e) {
        // بافت همین الان رفته (رویدادش هنوز نرسیده) ⇒ خطای ناشی از آن را به کاربر نشان نده؛ بازیابی خودش ادامه می‌دهد
        if (eng.g.lost) eng.ok = false;
        else pr.onError((e as Error).message);
      }
      dirty.current.present = true;
      const now = performance.now();
      if (now - lastHist.current > 160) {
        lastHist.current = now;
        const hs = eng.readSmall(200);
        if (hs) pr.onHistogram(histogram(hs.data));
        pr.onStatus(`ترکیب ${Math.round(now - t0)} میلی‌ثانیه`);
      }
    }
    if (dirty.current.present) {
      dirty.current.present = false;
      eng.setSelection(!photoModeRef.current && SEL_TOOLS.has(pr.tool) ? pr.selection.canvas : null, pr.selection.ver);
      const M = mul(g.M, [1 / dpr, 0, 0, 0, 1 / dpr, 0, 0, 0, 1]);
      const splitPx = pr.compare === "split" ? g.tToScreen(g.frame.x0 + g.frame.w * splitRef.current, 0)[0] * dpr : -1;
      eng.present(M, [bw, bh], { mode: photoModeRef.current ? "photo" : "canvas", before: pr.compare === "before", split: splitPx });
    }
  };
  const boxRef = useRef(box);
  boxRef.current = box;
  const splitRef = useRef(split);
  splitRef.current = split;

  useEffect(() => {
    dirty.current.render = true;
    schedule();
  }, [p.state.layers, p.state.adjust, p.state.curve, p.state.liquify, ready, tick, schedule, p.masks]);

  useEffect(() => {
    dirty.current.present = true;
    schedule();
  }, [geo, p.compare, split, p.selection.ver, p.tool, schedule, ready]);

  // ───────────────────────── ورودی‌ها
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const t = e.target;
      if (e.code === "Space" && !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement)) {
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
  const docPt = (sx: number, sy: number): Pt2 => geoRef.current!.toDoc(sx, sy);
  const eng = () => engineRef.current;

  const onWheel = (e: React.WheelEvent) => {
    const [mx, my] = local(e);
    const g = geoRef.current!;
    const old = g.s;
    const next = Math.max(g.fitS * 0.3, Math.min(10, old * Math.exp(-e.deltaY * 0.0015)));
    setView((v) => {
      const k = 1 - next / old;
      return { s: next, x: v.x + (mx - (box.w / 2 + v.x)) * k, y: v.y + (my - (box.h / 2 + v.y)) * k };
    });
  };

  const layerById = (id: string) => stateRef.current.layers.find((l) => l.id === id) ?? null;
  const patchLayer = (id: string, patch: Partial<Layer>, commit?: string) => {
    const f = (s: ProState): ProState => ({ ...s, layers: s.layers.map((l) => (l.id === id ? ({ ...l, ...patch } as Layer) : l)) });
    if (commit) p.hist.apply(commit, f);
    else p.hist.live(f);
  };

  /** نقطه روی کدام لایه است (بالاترین، قابل‌دیدن) */
  const hitLayer = (pt: Pt2): Layer | null => {
    const e = eng();
    if (!e) return null;
    const all = stateRef.current.layers;
    const ls = canonical(all);
    for (let i = ls.length - 1; i >= 0; i--) {
      const l = ls[i];
      if (effectivelyHidden(all, l)) continue; // لایهٔ پنهان، یا لایه‌ای داخلِ گروهِ پنهان
      if (l.type === "base") continue;
      if (l.type !== "image" && l.type !== "text" && l.type !== "shape") continue;
      if (isPaintLayer(l)) continue;
      if (l.type === "text" && l.tile) continue;
      const sz = e.layerSize(l);
      if (!sz) continue;
      const c = corners(l, sz, Wo, Ho);
      if (c.length && lineIntersectionPoint(pt, c)) return l;
    }
    return null;
  };

  const effLocked = (l: Layer) => effectivelyLocked(stateRef.current.layers, l);

  /** کادرِ محیطیِ لایه‌های دیدنیِ یک گروه (فضای سندِ نرمال) برای کادرِ خط‌چین و چسبیدن به خط‌های راهنما */
  const groupBoxDoc = (gid: string): { x0: number; y0: number; x1: number; y1: number } | null => {
    const e = eng();
    if (!e) return null;
    const all = stateRef.current.layers;
    const ids = new Set(descendantIds(all, gid));
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const l of all) {
      if (!ids.has(l.id) || effectivelyHidden(all, l) || !("cx" in l)) continue;
      const sz = e.layerSize(l);
      if (!sz) continue;
      for (const c of corners(l, sz, Wo, Ho)) {
        x0 = Math.min(x0, c[0]);
        y0 = Math.min(y0, c[1]);
        x1 = Math.max(x1, c[0]);
        y1 = Math.max(y1, c[1]);
      }
    }
    return x1 > x0 && y1 > y0 ? { x0, y0, x1, y1 } : null;
  };

  /** جابه‌جاییِ گروه (dx, dy در فضای سند) با چسبیدنِ لبه‌ها/مرکزِ کادرِ گروه به خط‌های راهنما */
  const snapGroup = (b: { x0: number; y0: number; x1: number; y1: number }, dx: number, dy: number): [number, number] => {
    const g = geoRef.current;
    if (!g) return [dx, dy];
    const bx = [b.x0 + dx, (b.x0 + b.x1) / 2 + dx, b.x1 + dx];
    const by = [b.y0 + dy, (b.y0 + b.y1) / 2 + dy, b.y1 + dy];
    const lines = [0, 1 / 3, 0.5, 2 / 3, 1];
    let bestX = SNAP_PX / (g.s * Wo);
    let bestY = SNAP_PX / (g.s * Ho);
    let ox = 0;
    let oy = 0;
    let gx: number | null = null;
    let gy: number | null = null;
    for (const v of bx) for (const ln of lines) if (Math.abs(v - ln) < bestX) { bestX = Math.abs(v - ln); ox = ln - v; gx = ln; }
    for (const v of by) for (const ln of lines) if (Math.abs(v - ln) < bestY) { bestY = Math.abs(v - ln); oy = ln - v; gy = ln; }
    setGuides({ x: gx, y: gy });
    return [dx + ox, dy + oy];
  };

  const handlePoints = (l: Layer) => {
    const e = eng();
    const g = geoRef.current;
    if (!e || !g) return null;
    const sz = e.layerSize(l);
    if (!sz) return null;
    const c = corners(l, sz, Wo, Ho);
    if (c.length !== 4) return null;
    const scr = c.map((q) => g.toScreen(q[0], q[1]));
    const mid = (a: [number, number], b: [number, number]): [number, number] => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const topMid = mid(scr[0], scr[1]);
    const botMid = mid(scr[2], scr[3]);
    // دستگیرهٔ چرخش: ۲۸ پیکسل بالاتر از وسطِ لبهٔ بالا (در جهتِ بیرونی)
    const cen = mid(scr[0], scr[2]);
    const dx = topMid[0] - cen[0];
    const dy = topMid[1] - cen[1];
    const len = Math.hypot(dx, dy) || 1;
    const rotH: [number, number] = [topMid[0] + (dx / len) * 28, topMid[1] + (dy / len) * 28];
    return { scr, topMid, botMid, rotH, cen, left: mid(scr[0], scr[3]), right: mid(scr[1], scr[2]) };
  };

  const snapMove = (l: Layer, cx: number, cy: number): [number, number] => {
    const e = eng();
    const g = geoRef.current;
    if (!e || !g || !("cx" in l)) return [cx, cy];
    const sz = e.layerSize(l);
    if (!sz) return [cx, cy];
    const probe = { ...l, cx, cy } as Layer;
    const c = corners(probe, sz, Wo, Ho);
    const xs = c.map((q) => q[0]);
    const ys = c.map((q) => q[1]);
    const bx = [Math.min(...xs), cx, Math.max(...xs)];
    const by = [Math.min(...ys), cy, Math.max(...ys)];
    const lines = [0, 1 / 3, 0.5, 2 / 3, 1];
    const thrX = SNAP_PX / (g.s * Wo);
    const thrY = SNAP_PX / (g.s * Ho);
    let gx: number | null = null;
    let gy: number | null = null;
    let bestX = thrX;
    let bestY = thrY;
    let ox = 0;
    let oy = 0;
    for (const b of bx) for (const ln of lines) if (Math.abs(b - ln) < bestX) { bestX = Math.abs(b - ln); ox = ln - b; gx = ln; }
    for (const b of by) for (const ln of lines) if (Math.abs(b - ln) < bestY) { bestY = Math.abs(b - ln); oy = ln - b; gy = ln; }
    setGuides({ x: gx, y: gy });
    return [cx + ox, cy + oy];
  };

  // ───────────────────────── مداد و ماسک
  const ensureMask = (id: string): string | null => {
    const l = layerById(id);
    if (!l) return null;
    if (l.mask && l.mask.type === "paint") return l.mask.id;
    const mid = Math.random().toString(36).slice(2, 10);
    const hidden = l.type === "adjust" || l.type === "retouch";
    p.masks.create(mid, !hidden);
    p.hist.apply(hidden ? "ماسکِ تهی" : "ماسک", (s) => ({
      ...s,
      layers: s.layers.map((x) => (x.id === id ? ({ ...x, mask: { type: "paint", id: mid, invert: false, rev: 0 } } as Layer) : x)),
    }));
    if (!hidden) {
      p.setOpts({ erase: true });
      p.onStatus("ماسکِ سفید ساخته شد؛ قلم بخش‌ها را پنهان می‌کند (X = برعکس)");
    }
    return mid;
  };

  const stampTo = (mid: string, a: [number, number], b: [number, number], white: boolean) => {
    const e = p.masks.get(mid);
    if (!e) return;
    const ctx = e.canvas.getContext("2d", { willReadFrequently: true })!;
    const W = e.canvas.width;
    const H = e.canvas.height;
    maskLine(ctx, a[0] * W, a[1] * H, b[0] * W, b[1] * H, Math.max(0.5, p.opts.size * W), p.opts.hardness, p.opts.flow, white);
    p.masks.touch(mid);
    dirty.current.render = true;
    schedule();
  };

  // ───────────────────────── اشاره‌گر
  const beginDrag = (e: React.PointerEvent, d: Drag) => {
    drag.current = d;
    (wrap.current as Element).setPointerCapture?.(e.pointerId);
  };

  // ───────────────────────── مایع‌سازی / قلمِ پرکردنِ هوشمند / قلم (Pen)
  /**
   * نقطهٔ بوم (کسری) ⇒ نقطهٔ عکس (کسری) و شعاعِ قلمِ مایع‌سازی به «کسری از پهنای عکس». اندازهٔ قلم به پیکسلِ بوم است (مثلِ دیگر قلم‌ها)؛
   * با قابِ چرخیده/برش‌خورده/مقیاس‌شده ضریبِ «پیکسلِ عکس بر پیکسلِ بوم» از نگاشتِ دو نقطهٔ نزدیک می‌آید. بیرونِ عکس (حاشیهٔ قاب) ⇒ null.
   */
  const lqAt = (pt: Pt2): { u: Pt2; r: number } | null => {
    const e = eng();
    if (!e) return null;
    const u = e.canvasToPhoto(pt[0], pt[1]);
    if (!u) return null;
    const dl = 0.01;
    const u1 = e.canvasToPhoto(pt[0] + dl, pt[1]) ?? e.canvasToPhoto(pt[0] - dl, pt[1]);
    const k = u1 ? Math.hypot((u1[0] - u[0]) * PW, (u1[1] - u[1]) * PH) / (dl * Wo) : PW / Wo; // پیکسلِ عکس بر پیکسلِ بوم
    return { u, r: (p.opts.liqSize * Wo * k) / PW };
  };

  /** یک تکهٔ ضربهٔ مایع‌سازی از a تا b (بومِ نرمال): نقطه‌ها به فاصلهٔ ~۰٫۱۸ شعاع */
  const lqStroke = (d: Extract<Drag, { k: "liq" }>, a: Pt2, b: Pt2, dwell = false) => {
    const store = p.liquify;
    const o = p.opts;
    const rate = 0.4 + 1.6 * o.liqRate;
    const lenPx = Math.hypot((b[0] - a[0]) * Wo, (b[1] - a[1]) * Ho);
    const step = Math.max(1, o.liqSize * Wo * 0.18);
    const n = dwell || o.liq !== "push" && lenPx < 1e-6 ? 1 : Math.max(1, Math.ceil(lenPx / step));
    for (let i = 1; i <= n; i++) {
      const q0: Pt2 = [a[0] + ((b[0] - a[0]) * (i - 1)) / n, a[1] + ((b[1] - a[1]) * (i - 1)) / n];
      const q1: Pt2 = [a[0] + ((b[0] - a[0]) * i) / n, a[1] + ((b[1] - a[1]) * i) / n];
      const s0 = lqAt(q0);
      const s1 = lqAt(q1);
      if (!s1) continue;
      if (o.liq === "push") {
        if (!s0 || (q0[0] === q1[0] && q0[1] === q1[1])) continue;
        store.forward((s0.u[0] + s1.u[0]) / 2, (s0.u[1] + s1.u[1]) / 2, s1.r, s1.u[0] - s0.u[0], s1.u[1] - s0.u[1], o.liqStrength);
      } else if (o.liq === "bloat") store.bloat(s1.u[0], s1.u[1], s1.r, o.liqStrength * 0.04 * rate);
      else if (o.liq === "pucker") store.bloat(s1.u[0], s1.u[1], s1.r, -o.liqStrength * 0.04 * rate);
      else store.reconstruct(s1.u[0], s1.u[1], s1.r, Math.min(1, o.liqStrength * 0.25 * rate));
      d.changed = true;
    }
    dirty.current.render = true;
    schedule();
  };

  /** قلمِ پرکردنِ هوشمند: دایره‌ای روی انتخاب (Alt = کم کردن)؛ هر دایره با سختیِ قلم */
  const gfStamp = (a: Pt2, b: Pt2, sub: boolean) => {
    const sel = p.selection;
    const W = sel.w;
    const H = sel.h;
    const r = Math.max(1, p.opts.size * W);
    const lenPx = Math.hypot((b[0] - a[0]) * W, (b[1] - a[1]) * H);
    const n = Math.max(1, Math.ceil(lenPx / Math.max(1, r * 0.25)));
    const hard = p.opts.hardness;
    for (let i = 1; i <= n; i++) {
      const x = (a[0] + ((b[0] - a[0]) * i) / n) * W;
      const y = (a[1] + ((b[1] - a[1]) * i) / n) * H;
      sel.paint((c) => {
        c.arc(x, y, r, 0, Math.PI * 2);
        if (hard < 0.98) {
          const gr = c.createRadialGradient(x, y, r * hard, x, y, r);
          const col = sub ? "0,0,0" : "255,255,255";
          gr.addColorStop(0, `rgba(${col},1)`);
          gr.addColorStop(1, `rgba(${col},0)`);
          c.fillStyle = gr;
        }
      }, sub ? "sub" : "add");
    }
    dirty.current.present = true;
    schedule();
  };

  const penNear = (q: Pt2, sx: number, sy: number, rad: number) => {
    const s = geoRef.current!.toScreen(q[0], q[1]);
    return Math.hypot(s[0] - sx, s[1] - sy) <= rad;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("[data-nodrag]")) return;
    const [sx, sy] = local(e);
    const g = geoRef.current!;
    const tool = p.tool;
    const pt = docPt(sx, sy);
    const inDoc = pt[0] >= 0 && pt[1] >= 0 && pt[0] <= 1 && pt[1] <= 1;

    if (p.compare === "split" && Math.abs(g.tToScreen(g.frame.x0 + g.frame.w * split, 0)[0] - sx) < 14) {
      beginDrag(e, { k: "split" });
      return;
    }
    if (tool === "hand" || spaceDown.current || e.button === 1) {
      beginDrag(e, { k: "pan", sx, sy, vx: view.x, vy: view.y });
      return;
    }
    if (e.button !== 0) return;

    switch (tool) {
      case "move": {
        const act = layerById(p.activeId ?? "");
        // دستگیره‌های لایهٔ فعال
        if (act && act.visible && !effLocked(act)) {
          const hp = handlePoints(act);
          if (hp) {
            const near = (q: [number, number]) => Math.hypot(q[0] - sx, q[1] - sy) < 12;
            if (near(hp.rotH)) {
              const a0 = Math.atan2((pt[1] - (act as { cy: number }).cy) * (Ho / Wo), pt[0] - (act as { cx: number }).cx);
              beginDrag(e, { k: "rotate", id: act.id, a0, rot0: (act as { rot: number }).rot ?? 0 });
              return;
            }
            const names = ["nw", "ne", "se", "sw"];
            for (let i = 0; i < 4; i++) {
              if (near(hp.scr[i])) {
                const cc = act as { cx: number; cy: number };
                const d0 = Math.hypot(pt[0] - cc.cx, (pt[1] - cc.cy) * (Ho / Wo)) || 1e-6;
                beginDrag(e, { k: "scale", id: act.id, handle: names[i], d0, layer: JSON.parse(JSON.stringify(act)) });
                return;
              }
            }
            if ((act.type === "text" || act.type === "shape") && (near(hp.left) || near(hp.right))) {
              beginDrag(e, { k: "scale", id: act.id, handle: near(hp.left) ? "w" : "e", d0: 1, layer: JSON.parse(JSON.stringify(act)) });
              return;
            }
            if (act.type === "shape" && (near(hp.topMid) || near(hp.botMid))) {
              beginDrag(e, { k: "scale", id: act.id, handle: near(hp.topMid) ? "n" : "s", d0: 1, layer: JSON.parse(JSON.stringify(act)) });
              return;
            }
          }
        }
        // گرادیانِ لایهٔ فعال
        if (act?.mask && (act.mask.type === "linear" || act.mask.type === "radial") && gradHandleHit(act, sx, sy, beginDrag, e)) return;
        const hit = hitLayer(pt);
        if (hit) {
          // گروهِ فعال و کشیدن روی یکی از لایه‌هایش ⇒ همهٔ نوادگانِ گروه با هم (یک گامِ تاریخچه)؛ کلیکِ بی‌کشیدن همان لایه را انتخاب می‌کند
          if (act && act.type === "group" && !effLocked(act)) {
            const ids = new Set(descendantIds(stateRef.current.layers, act.id));
            if (ids.has(hit.id)) {
              const orig: [string, Pt2][] = stateRef.current.layers.filter((l) => ids.has(l.id) && "cx" in l).map((l) => [l.id, [(l as { cx: number }).cx, (l as { cy: number }).cy] as Pt2]);
              beginDrag(e, { k: "gmove", id: act.id, hitId: hit.id, start: pt, orig, box: groupBoxDoc(act.id), moved: false });
              return;
            }
          }
          p.setActiveId(hit.id);
          if (!effLocked(hit) && "cx" in hit) {
            // لایه‌های پیوندشده (هم‌شناسهٔ link) با هم جابه‌جا می‌شوند (دورِ ۸)
            const lk = (hit as { link?: string }).link;
            const mates = lk ? stateRef.current.layers.filter((l) => (l as { link?: string }).link === lk && "cx" in l && !effLocked(l)) : [];
            if (mates.length > 1) {
              const orig: [string, Pt2][] = mates.map((l) => [l.id, [(l as { cx: number }).cx, (l as { cy: number }).cy] as Pt2]);
              beginDrag(e, { k: "gmove", id: hit.id, hitId: hit.id, start: pt, orig, box: null, moved: false });
              return;
            }
            beginDrag(e, { k: "move", id: hit.id, start: pt, c0: [hit.cx, hit.cy], moved: false });
          }
          return;
        }
        if (inDoc) {
          const base = stateRef.current.layers.find((l) => l.type === "base");
          p.setActiveId(base?.id ?? null);
          // «کالا وسطِ قاب»: کشیدن روی عکس (نه روی لایه‌ای رویش) عکس را در قاب جابه‌جا می‌کند
          const sp = specRef.current;
          const geo = sp?.social;
          if (sp && sp.cf && sp.cf.fit === "contain" && sp.cf.subject === "auto" && geo && geo.mode === "contain" && !p.state.layers.some((l) => l.type === "base" && l.locked)) {
            const [tw, th] = geo.size;
            const scale = geo.view ? geo.view.scale : geo.fg[0] / sp.gw; // پیکسلِ بوم به ازای پیکسلِ عکس
            const fw = sp.gw * scale;
            const fh = sp.gh * scale;
            const left = geo.view ? geo.view.left : geo.pos[0];
            const top = geo.view ? geo.view.top : geo.pos[1];
            const baseScale = Math.min(tw / sp.gw, th / sp.gh) * (1 - (2 * sp.cf.padding) / 100);
            beginDrag(e, { k: "photo", start: pt, c0: [(tw / 2 - left) / fw, (th / 2 - top) / fh], zoom: scale / baseScale, fw, fh, tw, th, moved: false });
          }
        }
        return;
      }
      case "text": {
        if (!inDoc) return;
        const hit = hitLayer(pt);
        if (hit && hit.type === "text") {
          p.setActiveId(hit.id);
          p.onToolChange("move");
          p.onNeedTextFocus();
          return;
        }
        const l = makeText(+pt[0].toFixed(4), +pt[1].toFixed(4));
        p.hist.apply("متن", (s) => ({ ...s, layers: [...s.layers, l] }));
        p.setActiveId(l.id);
        p.onToolChange("move");
        p.onNeedTextFocus();
        return;
      }
      case "brush": {
        let id = p.activeId;
        if (!id) return p.onStatus("اول یک لایه را انتخاب کنید (یا «قلمِ تنظیمِ موضعی» را بزنید).");
        const l = layerById(id);
        if (!l || l.locked) return p.onStatus("این لایه قفل است.");
        const mid = ensureMask(id);
        if (!mid) return;
        const white = !p.opts.erase;
        const a: [number, number] = [pt[0], pt[1]];
        stampTo(mid, a, a, white);
        beginDrag(e, { k: "paint", id, last: a, white });
        id = null;
        return;
      }
      case "paint":
      case "pencil":
      case "eraser":
      case "history":
      case "blur":
      case "sharpen":
      case "dodge":
      case "burn":
      case "sponge":
      case "smudge": {
        if (e.altKey && (tool === "paint" || tool === "pencil")) {
          if (inDoc) p.onPickColor(pt[0], pt[1]);
          return;
        }
        if (!inDoc) return;
        const act0 = layerById(p.activeId ?? "");
        if (tool === "eraser" && !isPaintLayer(act0)) {
          // پاک‌کن روی لایهٔ عادی = سیاه‌کردنِ ماسکِ لایه (غیرمخرب)؛ روی لایهٔ نقاشی = پاک‌کردنِ پیکسل‌ها
          const id0 = p.activeId;
          if (!id0 || !act0) return p.onStatus("اول لایه‌ای را انتخاب کنید؛ پاک‌کن روی لایه‌های عادی بخشی را با ماسکِ لایه پنهان می‌کند.");
          if (effLocked(act0)) return p.onStatus("این لایه قفل است.");
          const mid = ensureMask(id0);
          if (!mid) return;
          const a0: [number, number] = [pt[0], pt[1]];
          stampTo(mid, a0, a0, false);
          beginDrag(e, { k: "paint", id: id0, last: a0, white: false });
          return;
        }
        if (act0 && isPaintLayer(act0) && (effLocked(act0) || !act0.visible)) return p.onStatus(effLocked(act0) ? "این لایهٔ نقاشی قفل است." : "لایهٔ نقاشی پنهان است؛ اول نمایشش دهید.");
        let hsrc: HTMLCanvasElement | null = null;
        if (tool === "history" || isSampleTool(tool)) {
          hsrc = p.historySource();
          if (!hsrc) return p.onStatus(tool === "history" ? "منبعِ قلمِ تاریخچه آماده نیست؛ در زبانهٔ «تاریخچه» یک عکسِ لحظه‌ای را به‌عنوانِ منبع انتخاب کنید." : "تصویرِ نمونه هنوز آماده نیست؛ چند لحظه بعد دوباره امتحان کنید.");
        }
        const pl = p.ensurePaint();
        if (!pl) return;
        const ent = p.paints.get(pl.paintId);
        if (!ent) return;
        const mode: StrokeMode = tool === "paint" ? "paint" : tool === "pencil" ? "pencil" : tool === "eraser" ? "erase" : tool === "smudge" ? "smudge" : "history";
        const cw = ent.canvas.width;
        const ch = ent.canvas.height;
        const clip = p.selection.active && p.selection.canvas ? selectionAlpha(p.selection.canvas, cw, ch) : null;
        const ss = new StrokeSession(ent.canvas, mode, { color: p.opts.color, size: p.opts.size, hardness: p.opts.hardness, opacity: p.opts.flow, kind: p.opts.brushKind, spacing: p.opts.brushSpacing, scatter: p.opts.brushScatter, tip: tool === "paint" || tool === "eraser" ? p.brushTip() : null }, hsrc, clip);
        ss.line(pt[0] * cw, pt[1] * ch, pt[0] * cw, pt[1] * ch);
        p.paints.touch(pl.paintId);
        dirty.current.render = true;
        schedule();
        const label = mode === "paint" ? "نقاشی" : mode === "pencil" ? "مداد" : mode === "erase" ? "پاک‌کردنِ نقاشی" : mode === "smudge" ? "لکه‌کش" : tool === "blur" ? "محو" : tool === "sharpen" ? "تیز" : tool === "dodge" ? "روشن‌کردن" : tool === "burn" ? "تیره‌کردن" : tool === "sponge" ? "اسفنج" : "قلمِ تاریخچه";
        beginDrag(e, { k: "pt", layerId: pl.layerId, paintId: pl.paintId, ss, last: [pt[0], pt[1]], label });
        return;
      }
      case "bucket":
        if (inDoc) p.onBucket(pt[0], pt[1]);
        return;
      case "picker":
        if (inDoc) p.onPickColor(pt[0], pt[1]);
        return;
      case "gradient": {
        if (!inDoc) return;
        const act = layerById(p.activeId ?? "");
        if (act?.mask && (act.mask.type === "linear" || act.mask.type === "radial") && gradHandleHit(act, sx, sy, beginDrag, e)) return;
        const kind = p.opts.gradKind;
        const mask = kind === "linear"
          ? { type: "linear" as const, p0: pt, p1: [pt[0], pt[1] + 0.001] as Pt2, invert: false }
          : { type: "radial" as const, c: pt, rx: 0.001, ry: 0.001, feather: 0.6, invert: false };
        const nl: AdjustLayer = { ...makeAdjust(kind === "linear" ? "شیبِ خطی" : "شیبِ شعاعی", { exposure: 0.5 }), mask };
        p.hist.live((s) => ({ ...s, layers: [...s.layers, nl] }));
        p.setActiveId(nl.id);
        beginDrag(e, { k: "grad", id: nl.id, p0: pt, kind });
        return;
      }
      case "clone":
      case "heal": {
        if (!inDoc) return;
        if (e.altKey) {
          cloneRef.current = { pending: pt, offset: null };
          setCloneSrc(pt);
          p.onStatus("منبع انتخاب شد؛ حالا روی جای دیگر نقاشی کنید");
          return;
        }
        const cr = cloneRef.current;
        if (cr.pending) {
          cr.offset = [cr.pending[0] - pt[0], cr.pending[1] - pt[1]];
          cr.pending = null;
        }
        if (!cr.offset) return p.onStatus("اول Alt را نگه دارید و روی منبع کلیک کنید");
        const mode: Stroke["mode"] = tool === "heal" ? "heal" : "clone";
        const stroke: Stroke = { mode, pts: [pt], r: p.opts.size, hardness: p.opts.hardness, opacity: p.opts.flow, dx: cr.offset[0], dy: cr.offset[1] };
        const act = layerById(p.activeId ?? "");
        let rid: string;
        if (act && act.type === "retouch" && !act.locked) {
          rid = act.id;
          p.hist.live((s) => ({ ...s, layers: s.layers.map((l) => (l.id === rid ? ({ ...l, strokes: [...(l as RetouchLayer).strokes, stroke] } as Layer) : l)) }));
        } else {
          const nl = makeRetouch();
          nl.strokes = [stroke];
          rid = nl.id;
          p.hist.live((s) => ({ ...s, layers: [...s.layers, nl] }));
          p.setActiveId(rid);
        }
        beginDrag(e, { k: "stroke", id: rid });
        return;
      }
      case "spot": {
        if (!inDoc) return;
        const sp = stateRef.current.spots;
        const hit = sp.findIndex((s) => Math.hypot((s.x - pt[0]) * Wo, (s.y - pt[1]) * Ho) < s.r * Math.min(Wo, Ho) * 1.1);
        if (hit >= 0 || e.altKey) {
          if (hit >= 0) p.hist.apply("برداشتنِ لکه", (s) => ({ ...s, spots: s.spots.filter((_, i) => i !== hit) }));
          return;
        }
        p.hist.apply("ترمیمِ لکه", (s) => ({ ...s, spots: [...s.spots, { x: +pt[0].toFixed(4), y: +pt[1].toFixed(4), r: p.opts.spotR }] }));
        return;
      }
      case "marquee":
      case "ellipse":
      case "lasso": {
        const sel = p.selection;
        const mode: "new" | "add" | "sub" = e.altKey ? "sub" : e.shiftKey ? "add" : "new";
        const base = mode === "new" || !sel.canvas ? null : cloneCanvas(sel.canvas);
        beginDrag(e, { k: "sel", kind: tool, p0: pt, pts: [pt], base, mode });
        return;
      }
      case "subject":
        if (inDoc) p.onSubject();
        return;
      case "wb": {
        // نقطه روی بومِ نهایی است؛ قطره‌چکان از عکسِ بی‌تنظیم نمونه می‌گیرد ⇒ از قاب به عکس برگردان
        if (!inDoc) return;
        const ph = eng()?.canvasToPhoto(pt[0], pt[1]);
        if (ph) p.onWb(ph[0], ph[1]);
        else p.onStatus("این نقطه روی عکس نیست (حاشیهٔ قاب)");
        return;
      }
      case "redeye": {
        // کلیک روی چشم: لکهٔ قرمزِ دورِ نقطه روی بومِ کاری پیدا می‌شود (مرکز + شعاع)؛ نشد ⇒ شعاعِ لغزنده
        if (!inDoc) return;
        const full = eng()?.readFull();
        const est = full ? estimateEye(full.data, full.w, full.h, pt[0] * full.w, pt[1] * full.h, p.opts.eyeR * full.w) : null;
        const eye = est ?? { x: +pt[0].toFixed(5), y: +pt[1].toFixed(5), r: p.opts.eyeR };
        const act = layerById(p.activeId ?? "");
        if (act && act.type === "redeye" && !act.locked) {
          if (act.eyes.length >= 16) return p.onStatus("در یک لایه بیشتر از ۱۶ چشم نمی‌شود؛ یک لایهٔ قرمزیِ چشمِ دیگر بسازید.");
          p.hist.apply("قرمزیِ چشم", (s) => ({ ...s, layers: s.layers.map((l) => (l.id === act.id && l.type === "redeye" ? { ...l, eyes: [...l.eyes, eye] } : l)) }));
        } else {
          const nl = makeRedeye([eye]);
          nl.amount = p.opts.eyeAmount;
          nl.darken = p.opts.eyeDarken;
          p.hist.apply("قرمزیِ چشم", (s) => ({ ...s, layers: [...s.layers, nl] }));
          p.setActiveId(nl.id);
        }
        p.onStatus(est ? "چشم پیدا شد و اصلاح شد؛ روی چشمِ بعدی کلیک کنید" : "لکهٔ قرمز پیدا نشد؛ با اندازهٔ لغزنده اصلاح شد (اندازه را با لغزنده تنظیم کنید)");
        return;
      }
      case "liquify": {
        if (!inDoc) return;
        if (!lqAt(pt)) return p.onStatus("این نقطه روی عکس نیست (حاشیهٔ قاب)؛ مایع‌سازی فقط روی خودِ عکس کار می‌کند.");
        if (drag.current?.k === "liq") window.clearInterval(drag.current.timer); // (دومین انگشت/اشاره‌گر: زمان‌سنجِ قبلی نشت نکند)
        const d: Extract<Drag, { k: "liq" }> = { k: "liq", last: pt, changed: false, t: performance.now(), timer: 0 };
        if (p.opts.liq !== "push") {
          lqStroke(d, pt, pt, true);
          // نگه‌داشتنِ قلم روی یک نقطه (باد/جمع/بازسازی) ⇒ هر ۶۰ میلی‌ثانیه یک ضربه، تا وقتی نشانگر تکان نمی‌خورد
          d.timer = window.setInterval(() => {
            if (performance.now() - d.t > 90) lqStroke(d, d.last, d.last, true);
          }, 60);
        }
        beginDrag(e, d);
        return;
      }
      case "genfill": {
        if (!inDoc) return;
        const sub = e.altKey;
        gfStamp(pt, pt, sub);
        beginDrag(e, { k: "gf", last: pt, sub });
        return;
      }
      case "pen": {
        const pen = p.pen;
        // دستگیره‌ها (بالاتر از نقطه‌ها)
        for (let i = pen.pts.length - 1; i >= 0; i--) {
          const a = pen.pts[i];
          for (const which of ["ho", "hi"] as const) {
            const h = a[which];
            if (h && penNear([a.x + h[0], a.y + h[1]], sx, sy, 8)) {
              beginDrag(e, { k: "pen", kind: which, i, start: pt, orig: [a.x, a.y], sx, sy, moved: false, smooth: pen.isSmooth(i, Wo, Ho) });
              return;
            }
          }
        }
        for (let i = pen.pts.length - 1; i >= 0; i--) {
          const a = pen.pts[i];
          if (!penNear([a.x, a.y], sx, sy, 10)) continue;
          if (e.shiftKey) {
            pen.removeAt(i); // Shift + کلیک روی نقطه = برداشتنِ آن نقطه
            p.onPenChange();
            p.onStatus("نقطه برداشته شد");
            return;
          }
          if (i === 0 && !pen.finished && pen.pts.length >= 3) {
            pen.close(); // کلیک روی نقطهٔ اول = بستنِ مسیر
            p.onPenChange();
            p.onStatus("مسیر بسته شد؛ از نوارِ بالا انتخاب/ماسک/لایهٔ شکل بسازید");
            return;
          }
          if (e.altKey) {
            pen.toggleSmooth(i); // Alt + کلیک: گوشه ⇄ نرم
            p.onPenChange();
            return;
          }
          pen.sel = i;
          p.onPenChange();
          beginDrag(e, { k: "pen", kind: "anchor", i, start: pt, orig: [a.x, a.y], sx, sy, moved: false, smooth: false });
          return;
        }
        // کلیک روی خودِ مسیر (مسیرِ تمام‌شده، یا Ctrl در مسیرِ در حالِ رسم) = افزودنِ نقطه روی همان پاره؛ شکلِ خم عوض نمی‌شود
        if (pen.segCount > 0 && (pen.finished || e.ctrlKey || e.metaKey) && pen.pts.length < PEN_MAX) {
          const hit = pen.nearestSegment((x, y) => geoRef.current!.toScreen(x, y), sx, sy);
          if (hit && hit.d <= 7) {
            const i = pen.insertAt(hit.seg, hit.t);
            if (i >= 0) {
              const a = pen.pts[i];
              p.onPenChange();
              p.onStatus("نقطه افزوده شد؛ بکشیدش تا جابه‌جا شود");
              beginDrag(e, { k: "pen", kind: "anchor", i, start: pt, orig: [a.x, a.y], sx, sy, moved: false, smooth: false });
              return;
            }
          }
        }
        if (pen.finished) pen.clear(); // مسیرِ تمام‌شده + کلیک روی جای خالی = مسیرِ تازه
        if (pen.pts.length >= PEN_MAX) return p.onStatus(`مسیر بیشتر از ${PEN_MAX} نقطه نمی‌شود.`);
        const i = pen.add(+pt[0].toFixed(5), +pt[1].toFixed(5));
        p.onPenChange();
        beginDrag(e, { k: "pen", kind: "new", i, start: pt, orig: pt, sx, sy, moved: false, smooth: false });
        return;
      }
      case "crop": {
        // دستگیره‌ها و خودِ قاب با DOM کار می‌کنند؛ کشیدن بیرونِ قاب = قابِ تازه از همان نقطه
        const [tx, ty] = g.screenToT(sx, sy);
        beginDrag(e, { k: "cropnew", fx: Math.max(0, Math.min(1, tx / g.Wt)), fy: Math.max(0, Math.min(1, ty / g.Ht)) });
        return;
      }
      case "persp":
      default:
        return;
    }
  };

  /** اگر روی دستگیرهٔ گرادیانِ لایه کلیک شد، کشیدن را شروع کن */
  const gradHandleHit = (l: Layer, sx: number, sy: number, begin: (e: React.PointerEvent, d: Drag) => void, e: React.PointerEvent): boolean => {
    const g = geoRef.current!;
    if (!l.mask) return false;
    const near = (q: Pt2) => {
      const s = g.toScreen(q[0], q[1]);
      return Math.hypot(s[0] - sx, s[1] - sy) < 13;
    };
    if (l.mask.type === "linear") {
      if (near(l.mask.p0)) return begin(e, { k: "gh", id: l.id, which: "p0" }), true;
      if (near(l.mask.p1)) return begin(e, { k: "gh", id: l.id, which: "p1" }), true;
    } else if (l.mask.type === "radial") {
      if (near(l.mask.c)) return begin(e, { k: "gh", id: l.id, which: "c" }), true;
      if (near([l.mask.c[0] + l.mask.rx, l.mask.c[1]])) return begin(e, { k: "gh", id: l.id, which: "r" }), true;
    }
    return false;
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const [sx, sy] = local(e);
    const g = geoRef.current!;
    if (CURSOR_TOOLS.has(p.tool) || (p.tool === "pen" && p.pen.active)) setCursor([sx, sy]);
    else if (cursor) setCursor(null);
    const d = drag.current;
    if (!d) return;
    const pt = docPt(sx, sy);
    switch (d.k) {
      case "pan":
        setView((v) => ({ s: v.s ?? g.fitS, x: d.vx + (sx - d.sx), y: d.vy + (sy - d.sy) }));
        break;
      case "split": {
        const [tx] = g.screenToT(sx, sy);
        setSplit(Math.max(0.02, Math.min(0.98, (tx - g.frame.x0) / g.frame.w)));
        break;
      }
      case "crop": {
        const dx = (sx - d.sx) / g.s / g.Wt;
        const dy = (sy - d.sy) / g.s / g.Ht;
        const r = nextCrop(d.rect, d.handle, dx, dy, p.aspect, g.Wt, g.Ht);
        p.hist.live((s) => ({ ...s, crop: r }));
        break;
      }
      case "cropnew": {
        const [tx, ty] = g.screenToT(sx, sy);
        const c01 = (v: number) => Math.max(0, Math.min(1, v));
        let x2 = c01(tx / g.Wt);
        let y2 = c01(ty / g.Ht);
        const dx = x2 - d.fx;
        const dy = y2 - d.fy;
        if (Math.abs(dx * g.Wt) < 4 && Math.abs(dy * g.Ht) < 4) break; // فقط یک لمس
        const ratio = p.aspect;
        if (ratio && ratio > 0) {
          // نسبتِ قفل: پهنا راننده است، ارتفاع از نسبت می‌آید؛ اگر از عکس بیرون زد پهنا کم می‌شود
          const sgnX = dx < 0 ? -1 : 1;
          const sgnY = dy < 0 ? -1 : 1;
          let wpx = Math.abs(dx) * g.Wt;
          let hpx = wpx / ratio;
          const roomH = (sgnY < 0 ? d.fy : 1 - d.fy) * g.Ht;
          if (hpx > roomH) {
            hpx = roomH;
            wpx = hpx * ratio;
          }
          x2 = c01(d.fx + (sgnX * wpx) / g.Wt);
          y2 = c01(d.fy + (sgnY * hpx) / g.Ht);
        }
        const r: Rect = { x: Math.min(d.fx, x2), y: Math.min(d.fy, y2), w: Math.abs(x2 - d.fx), h: Math.abs(y2 - d.fy) };
        if (r.w >= 0.02 && r.h >= 0.02) p.hist.live((s) => ({ ...s, crop: r }));
        break;
      }
      case "move": {
        const l = layerById(d.id);
        if (!l || !("cx" in l)) break;
        const nx = d.c0[0] + (pt[0] - d.start[0]);
        const ny = d.c0[1] + (pt[1] - d.start[1]);
        if (!d.moved && Math.hypot(pt[0] - d.start[0], pt[1] - d.start[1]) * Wo * g.s < 3) break;
        d.moved = true;
        const [sx2, sy2] = e.ctrlKey ? [nx, ny] : snapMove(l, nx, ny);
        patchLayer(d.id, { cx: +sx2.toFixed(5), cy: +sy2.toFixed(5) } as Partial<Layer>);
        break;
      }
      case "photo": {
        // pt بر پایهٔ بومِ نهایی (۰..۱) است؛ جابه‌جاییِ عکس در قاب = مرکزِ دوربین در جهتِ مخالف (به کسری از عکس)
        if (!d.moved && Math.hypot(pt[0] - d.start[0], pt[1] - d.start[1]) * Wo * g.s < 3) break;
        d.moved = true;
        const view = normalizeView([d.zoom, d.c0[0] - ((pt[0] - d.start[0]) * d.tw) / d.fw, d.c0[1] - ((pt[1] - d.start[1]) * d.th) / d.fh]);
        if (view.length !== 3) break;
        p.hist.live((s) => {
          const raw = s.tools.crop_format;
          if (!raw) return s;
          const cf = normalizeCropFormat(raw);
          return { ...s, tools: { ...s.tools, crop_format: cropFormatOpParams({ ...cf, view }) } };
        });
        break;
      }
      case "gmove": {
        const dx0 = pt[0] - d.start[0];
        const dy0 = pt[1] - d.start[1];
        if (!d.moved && Math.hypot(dx0, dy0) * Wo * g.s < 3) break;
        d.moved = true;
        const [dx, dy] = e.ctrlKey || !d.box ? [dx0, dy0] : snapGroup(d.box, dx0, dy0);
        const orig = new Map(d.orig);
        p.hist.live((s) => ({
          ...s,
          layers: s.layers.map((l) => {
            const o = orig.get(l.id);
            return o ? ({ ...l, cx: +(o[0] + dx).toFixed(5), cy: +(o[1] + dy).toFixed(5) } as Layer) : l;
          }),
        }));
        break;
      }
      case "scale": {
        const l0 = d.layer as Layer & { cx: number; cy: number };
        const ratio = Math.max(0.02, Math.hypot(pt[0] - l0.cx, (pt[1] - l0.cy) * (Ho / Wo)) / d.d0);
        const patch: Record<string, unknown> = {};
        if (d.handle === "e" || d.handle === "w") {
          // پهنای جعبه (متن) یا پهنای شکل
          const half = Math.abs((pt[0] - l0.cx) * Math.cos(rad((l0 as { rot?: number }).rot ?? 0)) + (pt[1] - l0.cy) * (Ho / Wo) * Math.sin(rad((l0 as { rot?: number }).rot ?? 0)));
          if (l0.type === "text") patch.width = +Math.max(0.05, Math.min(1.5, half * 2)).toFixed(4);
          else if (l0.type === "shape") patch.w = +Math.max(0.005, half * 2).toFixed(4);
        } else if (d.handle === "n" || d.handle === "s") {
          const r = rad((l0 as { rot?: number }).rot ?? 0);
          const half = Math.abs(-(pt[0] - l0.cx) * Math.sin(r) + (pt[1] - l0.cy) * (Ho / Wo) * Math.cos(r));
          if (l0.type === "shape") patch.h = +Math.max(0, half * 2).toFixed(4);
        } else if (l0.type === "image") patch.w = +Math.max(0.01, l0.w * ratio).toFixed(4);
        else if (l0.type === "text") {
          patch.size = +Math.max(0.005, Math.min(0.5, l0.size * ratio)).toFixed(4);
          if (l0.width > 0) patch.width = +Math.max(0.05, l0.width * ratio).toFixed(4);
          patch.lines = undefined;
        } else if (l0.type === "shape") {
          patch.w = +Math.max(0.005, l0.w * ratio).toFixed(4);
          patch.h = +Math.max(0, l0.h * ratio).toFixed(4);
        }
        patchLayer(d.id, patch as Partial<Layer>);
        break;
      }
      case "rotate": {
        const l = layerById(d.id) as (Layer & { cx: number; cy: number }) | null;
        if (!l) break;
        const a = Math.atan2((pt[1] - l.cy) * (Ho / Wo), pt[0] - l.cx);
        let rot = d.rot0 + ((a - d.a0) * 180) / Math.PI;
        rot = ((rot + 540) % 360) - 180;
        if (e.shiftKey) rot = Math.round(rot / 15) * 15;
        patchLayer(d.id, { rot: +rot.toFixed(1) } as Partial<Layer>);
        break;
      }
      case "paint": {
        const l = layerById(d.id);
        if (!l || !l.mask || l.mask.type !== "paint") break;
        const cur: [number, number] = [pt[0], pt[1]];
        stampTo(l.mask.id, d.last, cur, d.white);
        d.last = cur;
        break;
      }
      case "pt": {
        const ent = p.paints.get(d.paintId);
        if (!ent) break;
        const cw = ent.canvas.width;
        const ch = ent.canvas.height;
        const cur: [number, number] = [pt[0], pt[1]];
        d.ss.line(d.last[0] * cw, d.last[1] * ch, cur[0] * cw, cur[1] * ch);
        d.last = cur;
        p.paints.touch(d.paintId);
        dirty.current.render = true;
        schedule();
        break;
      }
      case "grad": {
        const dx = pt[0] - d.p0[0];
        const dy = pt[1] - d.p0[1];
        if (d.kind === "linear") patchLayer(d.id, { mask: { type: "linear", p0: d.p0, p1: pt, invert: false } } as Partial<Layer>);
        else {
          const rx = Math.max(0.002, Math.abs(dx));
          const ry = e.shiftKey ? rx : Math.max(0.002, Math.abs(dy) * (Ho / Wo));
          patchLayer(d.id, { mask: { type: "radial", c: d.p0, rx, ry, feather: 0.6, invert: false } } as Partial<Layer>);
        }
        break;
      }
      case "gh": {
        const l = layerById(d.id);
        if (!l?.mask) break;
        const m = l.mask;
        if (m.type === "linear") patchLayer(d.id, { mask: { ...m, [d.which]: pt } } as Partial<Layer>);
        else if (m.type === "radial") {
          if (d.which === "c") patchLayer(d.id, { mask: { ...m, c: pt } } as Partial<Layer>);
          else {
            const rx = Math.max(0.002, Math.abs(pt[0] - m.c[0]));
            patchLayer(d.id, { mask: { ...m, rx, ry: e.shiftKey ? rx : Math.max(0.002, rx * (m.ry / m.rx)) } } as Partial<Layer>);
          }
        }
        break;
      }
      case "stroke": {
        const l = layerById(d.id) as RetouchLayer | null;
        if (!l) break;
        const last = l.strokes[l.strokes.length - 1];
        const lp = last.pts[last.pts.length - 1];
        if (Math.hypot((pt[0] - lp[0]) * Wo, (pt[1] - lp[1]) * Ho) < Math.max(1.5, last.r * Wo * 0.1)) break;
        const ns: Stroke = { ...last, pts: [...last.pts, pt] };
        patchLayer(d.id, { strokes: [...l.strokes.slice(0, -1), ns] } as Partial<Layer>);
        break;
      }
      case "sel": {
        d.pts.push(pt);
        updateSelection(d, e.shiftKey && d.kind !== "lasso");
        break;
      }
      case "quad": {
        const q = stateRef.current.persp ?? { tl: [0, 0], tr: [1, 0], br: [1, 1], bl: [0, 1] } as Quad;
        const np: Quad = { ...q, [d.corner]: [Math.max(-0.5, Math.min(1.5, pt[0])), Math.max(-0.5, Math.min(1.5, pt[1]))] as Pt2 };
        p.hist.live((s) => ({ ...s, persp: np }));
        break;
      }
      case "liq": {
        d.t = performance.now();
        lqStroke(d, d.last, pt);
        d.last = pt;
        break;
      }
      case "gf": {
        gfStamp(d.last, pt, d.sub);
        d.last = pt;
        break;
      }
      case "pen": {
        const pen = p.pen;
        const a = pen.pts[d.i];
        if (!a) break;
        if (d.kind === "new") {
          if (!d.moved && Math.hypot(sx - d.sx, sy - d.sy) < 4) break;
          d.moved = true;
          // کشیدن بعد از کلیک = دستگیره‌های نرمِ متقارن (خروجی به سمتِ کشیدن)
          const dx = pt[0] - a.x;
          const dy = pt[1] - a.y;
          a.ho = [dx, dy];
          a.hi = [-dx, -dy];
        } else if (d.kind === "anchor") {
          if (!d.moved && Math.hypot(sx - d.sx, sy - d.sy) < 3) break;
          d.moved = true;
          a.x = +(d.orig[0] + (pt[0] - d.start[0])).toFixed(5);
          a.y = +(d.orig[1] + (pt[1] - d.start[1])).toFixed(5);
        } else {
          d.moved = true;
          const mine = d.kind;
          const other = mine === "ho" ? "hi" : "ho";
          const v: Pt2 = [pt[0] - a.x, pt[1] - a.y];
          a[mine] = v;
          // نقطهٔ نرم: دستگیرهٔ مقابل هم‌راستا می‌ماند و طولش را نگه می‌دارد (Alt = جدا)
          if (d.smooth && !e.altKey && a[other]) {
            const o = a[other]!;
            const lo = Math.hypot(o[0] * Wo, o[1] * Ho);
            const lv = Math.hypot(v[0] * Wo, v[1] * Ho) || 1;
            a[other] = [(-v[0] * lo) / lv, (-v[1] * lo) / lv];
          }
        }
        pen.touch();
        p.onPenChange();
        break;
      }
    }
  };

  const updateSelection = (d: Extract<Drag, { k: "sel" }>, square: boolean) => {
    const sel = p.selection;
    const W = sel.w;
    const H = sel.h;
    sel.canvas = d.base ? cloneCanvas(d.base) : null;
    const [x0, y0] = [d.p0[0] * W, d.p0[1] * H];
    const last = d.pts[d.pts.length - 1];
    let [x1, y1] = [last[0] * W, last[1] * H];
    if (square) {
      const s = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
      x1 = x0 + Math.sign(x1 - x0 || 1) * s;
      y1 = y0 + Math.sign(y1 - y0 || 1) * s;
    }
    sel.paint((c) => {
      if (d.kind === "marquee") c.rect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      else if (d.kind === "ellipse") c.ellipse((x0 + x1) / 2, (y0 + y1) / 2, Math.abs(x1 - x0) / 2, Math.abs(y1 - y0) / 2, 0, 0, Math.PI * 2);
      else {
        d.pts.forEach((q, i) => (i ? c.lineTo(q[0] * W, q[1] * H) : c.moveTo(q[0] * W, q[1] * H)));
        c.closePath();
      }
    }, d.mode === "new" || !d.base ? (d.base ? "add" : "new") : d.mode);
    dirty.current.present = true;
    schedule();
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    setGuides({ x: null, y: null });
    if (!d) return;
    switch (d.k) {
      case "crop":
      case "cropnew":
        p.hist.end("برش");
        break;
      case "move":
        if (d.moved) p.hist.end("جابه‌جایی");
        break;
      case "photo":
        if (d.moved) p.hist.end("جابه‌جاییِ عکس در قاب");
        break;
      case "gmove":
        if (d.moved) p.hist.end("جابه‌جاییِ گروه");
        else p.setActiveId(d.hitId);
        break;
      case "scale":
        p.hist.end("تغییر اندازه");
        break;
      case "rotate":
        p.hist.end("چرخش");
        break;
      case "paint": {
        const l = layerById(d.id);
        if (l?.mask && l.mask.type === "paint") {
          const mid = l.mask.id;
          const rev = (p.masks.revs.get(mid) ?? 0) + 1;
          p.masks.snapshot(mid, rev);
          p.hist.apply("نقاشی روی ماسک", (s) => ({
            ...s,
            layers: s.layers.map((x) => (x.id === d.id && x.mask?.type === "paint" ? ({ ...x, mask: { ...x.mask, rev } } as Layer) : x)),
          }));
          p.onMaskEdited(mid);
        }
        break;
      }
      case "pt": {
        const rev = (p.paints.revs.get(d.paintId) ?? 0) + 1;
        p.paints.snapshot(d.paintId, rev);
        p.hist.apply(d.label, (s) => ({
          ...s,
          layers: s.layers.map((x) => (x.id === d.layerId && x.type === "image" && x.src.kind === "paint" ? ({ ...x, src: { ...x.src, rev } } as Layer) : x)),
        }));
        break;
      }
      case "grad":
        p.hist.end("شیب");
        break;
      case "gh":
        p.hist.end("ویرایشِ شیب");
        break;
      case "stroke":
        p.hist.end("ضربهٔ روتوش");
        break;
      case "sel":
        p.onSelectionChange();
        break;
      case "quad":
        p.hist.end("پرسپکتیو");
        break;
      case "liq": {
        window.clearInterval(d.timer);
        if (d.changed) {
          // یک گام در تاریخچه به ازای هر ضربه؛ نسخهٔ نقشه با rev در state.liquify نگه داشته می‌شود
          const rev = p.liquify.commit();
          p.hist.apply("مایع‌سازی", (s) => ({ ...s, liquify: { rev } }));
        }
        break;
      }
      case "pen":
        p.onPenChange();
        break;
      case "gf":
        p.onSelectionChange();
        break;
      default:
        break;
    }
  };

  // ───────────────────────── دستگیره‌های DOM (برش و پرسپکتیو)
  const beginCrop = (e: React.PointerEvent, handle: Handle) => {
    e.stopPropagation();
    const [sx, sy] = local(e);
    beginDrag(e, { k: "crop", handle, sx, sy, rect: { ...p.state.crop } });
  };
  const beginQuad = (e: React.PointerEvent, corner: keyof Quad) => {
    e.stopPropagation();
    beginDrag(e, { k: "quad", corner });
  };

  // ───────────────────────── رویه‌ها
  const act = p.state.layers.find((l) => l.id === p.activeId) ?? null;
  const hp = p.tool === "move" && act && act.visible && "cx" in act ? handlePoints(act) : null;
  // گروه: دستگیرهٔ تبدیل ندارد؛ فقط کادرِ خط‌چینِ لایه‌های دیدنی‌اش
  const gbox = p.tool === "move" && act && act.type === "group" && act.visible ? groupBoxDoc(act.id) : null;
  const fr = geo.frameScreen();
  const cropR = (() => {
    const c = p.state.crop;
    const [x0, y0] = geo.tToScreen(c.x * geo.Wt, c.y * geo.Ht);
    const [x1, y1] = geo.tToScreen((c.x + c.w) * geo.Wt, (c.y + c.h) * geo.Ht);
    return { x0, y0, x1, y1 };
  })();
  const grid = p.opts.grid !== "off" || p.tool === "straighten";
  const gridKind = p.tool === "straighten" ? "fine" : p.opts.grid;
  const q = p.state.persp ?? { tl: [0, 0], tr: [1, 0], br: [1, 1], bl: [0, 1] } as Quad;
  const sc = (pt: Pt2) => geo.toScreen(pt[0], pt[1]);
  const gm = act?.mask && (act.mask.type === "linear" || act.mask.type === "radial") && (p.tool === "move" || p.tool === "gradient") ? act.mask : null;

  const cursorDia = ((p.tool === "liquify" ? p.opts.liqSize : p.tool === "redeye" ? p.opts.eyeR * 1.2 : p.opts.size) * Wo) * geo.s * 2;
  const cursorStyle = p.tool === "hand" ? "grab" : CROSS_TOOLS.includes(p.tool) ? "crosshair" : undefined;
  // قلم (Pen): خمِ در حالِ ساخت (+ ریسمانِ کشسان تا نشانگر)، نقطه‌ها و دستگیره‌ها
  const penOn = p.tool === "pen" && p.pen.active;
  const penCursor: Pt2 | null = penOn && !p.pen.finished && cursor ? docPt(cursor[0], cursor[1]) : null;
  const penD = penOn ? penSvgD(p.pen, (x, y) => geo.toScreen(x, y), penCursor) : "";

  return (
    <div
      ref={wrap}
      className="pv-wrap"
      data-testid="viewport"
      data-tool={p.tool}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={() => setCursor(null)}
      onContextMenu={(e) => e.preventDefault()}
      style={{ cursor: cursorStyle, touchAction: "none" }}
    >
      <canvas key={canvasGen} ref={canvas} className="pv-canvas" style={{ width: box.w, height: box.h }} data-testid="photo-canvas" />
      {glErr && <div className="vp-msg">{glErr}</div>}
      {loadErr && <div className="vp-msg">{loadErr}</div>}
      {!glErr && !loadErr && !glLost && !ready && <div className="vp-msg">در حالِ بارگذاری…</div>}
      {glLost && (
        <div className="pv-lost" role="status" data-testid="gl-lost" onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
          <span>اتصال به کارت گرافیک قطع شد؛ در حال بازیابی…</span>
          {glWaited && <button type="button" className="ws-btn" onClick={retryGl} data-testid="gl-retry">بازیابی</button>}
        </div>
      )}

      <svg className="pv-svg" width={box.w} height={box.h} aria-hidden="true">
        {grid && gridKind !== "off" && <GridLines kind={gridKind} fr={fr} />}
        {guides.x !== null && (() => { const a = sc([guides.x, 0]); const b = sc([guides.x, 1]); return <line className="pv-guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />; })()}
        {guides.y !== null && (() => { const a = sc([0, guides.y]); const b = sc([1, guides.y]); return <line className="pv-guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />; })()}
        {gbox && (() => {
          const a = sc([gbox.x0, gbox.y0]);
          const b = sc([gbox.x1, gbox.y1]);
          return <rect className="pv-gbox" data-testid="group-box" x={Math.min(a[0], b[0])} y={Math.min(a[1], b[1])} width={Math.abs(b[0] - a[0])} height={Math.abs(b[1] - a[1])} />;
        })()}
        {hp && (
          <g data-testid="layer-handles">
            <polygon className="pv-box" points={hp.scr.map((s) => s.join(",")).join(" ")} />
            <line className="pv-rotline" x1={hp.topMid[0]} y1={hp.topMid[1]} x2={hp.rotH[0]} y2={hp.rotH[1]} />
            <circle className="pv-handle pv-rot" cx={hp.rotH[0]} cy={hp.rotH[1]} r={6} data-handle="rotate" />
            {hp.scr.map((s, i) => <rect key={i} className="pv-handle" x={s[0] - 5} y={s[1] - 5} width={10} height={10} data-handle={["nw", "ne", "se", "sw"][i]} />)}
            {(act?.type === "text" || act?.type === "shape") && [hp.left, hp.right].map((s, i) => <rect key={`w${i}`} className="pv-handle pv-side" x={s[0] - 4} y={s[1] - 8} width={8} height={16} />)}
          </g>
        )}
        {gm && gm.type === "linear" && (() => {
          const a = sc(gm.p0); const b = sc(gm.p1);
          const dx = b[0] - a[0]; const dy = b[1] - a[1]; const len = Math.hypot(dx, dy) || 1;
          const nx = (-dy / len) * 400; const ny = (dx / len) * 400;
          return (
            <g data-testid="grad-handles">
              <line className="pv-grad" x1={a[0] - nx} y1={a[1] - ny} x2={a[0] + nx} y2={a[1] + ny} />
              <line className="pv-grad" x1={b[0] - nx} y1={b[1] - ny} x2={b[0] + nx} y2={b[1] + ny} />
              <line className="pv-grad dash" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />
              <circle className="pv-handle" cx={a[0]} cy={a[1]} r={6} />
              <circle className="pv-handle" cx={b[0]} cy={b[1]} r={6} />
            </g>
          );
        })()}
        {gm && gm.type === "radial" && (() => {
          const c = sc(gm.c); const r = sc([gm.c[0] + gm.rx, gm.c[1]]);
          const rxs = Math.abs(r[0] - c[0]); const rys = rxs * (gm.ry / gm.rx) * (Wo / Ho) * (Ho / Wo);
          return (
            <g data-testid="grad-handles">
              <ellipse className="pv-grad" cx={c[0]} cy={c[1]} rx={rxs} ry={rys} />
              <circle className="pv-handle" cx={c[0]} cy={c[1]} r={6} />
              <circle className="pv-handle" cx={r[0]} cy={r[1]} r={6} />
            </g>
          );
        })()}
        {p.tool === "spot" && p.state.spots.map((s, i) => {
          const c = sc([s.x, s.y]);
          return <circle key={i} className="pv-spot" cx={c[0]} cy={c[1]} r={s.r * Math.min(Wo, Ho) * geo.s} data-spot={i} />;
        })}
        {(p.tool === "clone" || p.tool === "heal") && cloneSrc && (() => {
          const c = sc(cloneSrc);
          return <g><circle className="pv-src" cx={c[0]} cy={c[1]} r={Math.max(6, cursorDia / 2)} /><line className="pv-src" x1={c[0] - 8} y1={c[1]} x2={c[0] + 8} y2={c[1]} /><line className="pv-src" x1={c[0]} y1={c[1] - 8} x2={c[0]} y2={c[1] + 8} /></g>;
        })()}
        {p.tool === "persp" && (
          <g data-testid="persp-overlay">
            <polygon className="pv-box" points={[q.tl, q.tr, q.br, q.bl].map((pt) => sc(pt).join(",")).join(" ")} />
            {(["tl", "tr", "br", "bl"] as (keyof Quad)[]).map((k) => { const c = sc(q[k]); return <circle key={k} className="pv-handle pv-quad" cx={c[0]} cy={c[1]} r={9} data-corner={k} data-nodrag="0" onPointerDown={(e) => beginQuad(e as unknown as React.PointerEvent, k)} style={{ pointerEvents: "all" }} />; })}
          </g>
        )}
        {cursor && CURSOR_TOOLS.has(p.tool) && <circle className="pv-cursor" cx={cursor[0]} cy={cursor[1]} r={Math.max(2, cursorDia / 2)} />}
        {penOn && (
          <g data-testid="pen-overlay" data-pen-points={p.pen.pts.length} data-pen-closed={p.pen.closed ? "1" : "0"}>
            {p.pen.closed && <path d={penD} fill="rgba(34,211,238,0.14)" stroke="none" />}
            <path d={penD} fill="none" stroke="#0b1220" strokeWidth={3.4} strokeLinejoin="round" strokeLinecap="round" opacity={0.55} />
            <path d={penD} fill="none" stroke="#22d3ee" strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
            {p.pen.pts.map((a, i) => {
              const c = geo.toScreen(a.x, a.y);
              const hs = (["ho", "hi"] as const).flatMap((w) => {
                const h = a[w];
                if (!h) return [];
                const q = geo.toScreen(a.x + h[0], a.y + h[1]);
                return [
                  <line key={`${i}${w}l`} x1={c[0]} y1={c[1]} x2={q[0]} y2={q[1]} stroke="#22d3ee" strokeWidth={1} opacity={0.8} />,
                  <circle key={`${i}${w}`} cx={q[0]} cy={q[1]} r={4} fill="#0b1220" stroke="#22d3ee" strokeWidth={1.4} data-pen-handle={`${i}${w}`} />,
                ];
              });
              const first = i === 0 && !p.pen.finished && p.pen.pts.length >= 3;
              return (
                <g key={i}>
                  {hs}
                  <rect x={c[0] - 5} y={c[1] - 5} width={10} height={10} fill={first ? "#22d3ee" : "#fff"} stroke="#0b1220" strokeWidth={1.4} data-pen-anchor={i} />
                </g>
              );
            })}
          </g>
        )}
      </svg>

      {p.tool === "crop" && (
        <div className="vp-crop" data-testid="crop-overlay">
          <i className="vp-shade" style={{ left: 0, top: 0, width: box.w, height: Math.max(0, cropR.y0) }} />
          <i className="vp-shade" style={{ left: 0, top: cropR.y1, width: box.w, height: Math.max(0, box.h - cropR.y1) }} />
          <i className="vp-shade" style={{ left: 0, top: cropR.y0, width: Math.max(0, cropR.x0), height: cropR.y1 - cropR.y0 }} />
          <i className="vp-shade" style={{ left: cropR.x1, top: cropR.y0, width: Math.max(0, box.w - cropR.x1), height: cropR.y1 - cropR.y0 }} />
          <div className={`vp-crop-box ${cropR.x1 - cropR.x0 < 64 || cropR.y1 - cropR.y0 < 64 ? "is-tiny" : ""}`} data-tiny={cropR.x1 - cropR.x0 < 64 || cropR.y1 - cropR.y0 < 64 ? "1" : "0"}
            style={{ left: cropR.x0, top: cropR.y0, width: cropR.x1 - cropR.x0, height: cropR.y1 - cropR.y0 }} onPointerDown={(e) => beginCrop(e, "move")}>
            <i className="third-v" style={{ left: "33.33%" }} />
            <i className="third-v" style={{ left: "66.66%" }} />
            <i className="third-h" style={{ top: "33.33%" }} />
            <i className="third-h" style={{ top: "66.66%" }} />
            {(["nw", "n", "ne", "e", "se", "s", "sw", "w"] as Handle[]).map((h) => (
              <b key={h} className={`vp-handle h-${h}`} data-handle={h} onPointerDown={(e) => beginCrop(e, h)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function GridLines({ kind, fr }: { kind: string; fr: { x0: number; y0: number; x1: number; y1: number } }) {
  const w = fr.x1 - fr.x0;
  const h = fr.y1 - fr.y0;
  const lines: [number, number, number, number][] = [];
  const v = (f: number) => lines.push([fr.x0 + w * f, fr.y0, fr.x0 + w * f, fr.y1]);
  const hz = (f: number) => lines.push([fr.x0, fr.y0 + h * f, fr.x1, fr.y0 + h * f]);
  if (kind === "thirds") [1 / 3, 2 / 3].forEach((f) => { v(f); hz(f); });
  else if (kind === "golden") [0.382, 0.618].forEach((f) => { v(f); hz(f); });
  else if (kind === "diag") { lines.push([fr.x0, fr.y0, fr.x1, fr.y1], [fr.x1, fr.y0, fr.x0, fr.y1]); }
  else for (let i = 1; i < 10; i++) { v(i / 10); hz(i / 10); }
  return <g>{lines.map((l, i) => <line key={i} className="pv-gridline" x1={l[0]} y1={l[1]} x2={l[2]} y2={l[3]} />)}</g>;
}

function cloneCanvas(c: HTMLCanvasElement): HTMLCanvasElement {
  const n = document.createElement("canvas");
  n.width = c.width;
  n.height = c.height;
  n.getContext("2d")!.drawImage(c, 0, 0);
  return n;
}

function histogram(data: Uint8ClampedArray) {
  const r = new Uint32Array(256);
  const g = new Uint32Array(256);
  const b = new Uint32Array(256);
  const l = new Uint32Array(256);
  let lo = 0;
  let hi = 0;
  const n = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    r[data[i]]++;
    g[data[i + 1]]++;
    b[data[i + 2]]++;
    const y = Math.round(0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]);
    l[y]++;
    if (data[i] >= 253 || data[i + 1] >= 253 || data[i + 2] >= 253) hi++;
    if (data[i] <= 2 && data[i + 1] <= 2 && data[i + 2] <= 2) lo++;
  }
  return { r, g, b, l, clipLo: lo / n, clipHi: hi / n };
}
