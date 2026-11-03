import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Asset } from "../api";
import { FULL, Rect } from "../manual/model";
import { nextCrop } from "../manual/Viewport";
import { Geo, GeoState, ViewState, mul } from "./geo";
import { ProEngine } from "./gl/engine";
import { maskLine } from "./gl/raster";
import type { Hist } from "./panelTypes";
import { MaskStore, Selection, ToolId, ToolOpts, ZoomCmd } from "./session";
import {
  AdjustLayer, Layer, ProState, Pt2, Quad, RetouchLayer, Stroke, makeAdjust, makeRetouch, makeText,
} from "./types";

export type StageApi = {
  engine: ProEngine;
  geo: () => Geo | null;
  redraw: () => void;
  layerSize: (l: Layer) => { w: number; h: number } | null;
  thumbnail: (adjust: Record<string, number>, curve: Record<string, [number, number][]>, size: number) => string | null;
  readFull: () => { data: Uint8ClampedArray; w: number; h: number } | null;
};

type Props = {
  src: string;
  origW: number;
  origH: number;
  state: ProState;
  hist: Hist;
  tool: ToolId;
  opts: ToolOpts;
  setOpts: (p: Partial<ToolOpts>) => void;
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  masks: MaskStore;
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
  | { k: "move"; id: string; start: Pt2; c0: Pt2; moved: boolean }
  | { k: "scale"; id: string; handle: string; d0: number; layer: Layer }
  | { k: "rotate"; id: string; a0: number; rot0: number }
  | { k: "paint"; id: string; last: [number, number]; white: boolean }
  | { k: "grad"; id: string; p0: Pt2; kind: "linear" | "radial" }
  | { k: "gh"; id: string; which: "p0" | "p1" | "c" | "r" }
  | { k: "stroke"; id: string }
  | { k: "sel"; kind: "marquee" | "ellipse" | "lasso"; p0: Pt2; pts: Pt2[]; base: HTMLCanvasElement | null; mode: "new" | "add" | "sub" }
  | { k: "quad"; corner: keyof Quad };

const SNAP_PX = 7;
const SEL_TOOLS = new Set<ToolId>(["marquee", "ellipse", "lasso", "subject"]);

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

  const Wo = p.origW;
  const Ho = p.origH;

  // ───────────────────────── موتور
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    let eng: ProEngine;
    try {
      eng = new ProEngine(cv);
    } catch (e) {
      setGlErr((e as Error).message);
      return;
    }
    engineRef.current = eng;
    eng.onNeedRender = () => {
      dirty.current.render = true;
      setTick((t) => t + 1);
    };
    p.onReady({
      engine: eng,
      geo: () => geoRef.current,
      redraw: () => {
        dirty.current.render = true;
        dirty.current.present = true;
        schedule();
      },
      layerSize: (l) => eng.layerSize(l),
      thumbnail: (a, c, size) => eng.thumbnail(a, c, size),
      readFull: () => eng.readFull(),
    });
    return () => {
      engineRef.current = null;
      cancelAnimationFrame(raf.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (stop) return;
      eng.setBase(img, Wo, Ho);
      p.masks.setSize(eng.Wd, eng.Hd);
      p.selection.setSize(eng.Wd, eng.Hd);
      dirty.current.render = true;
      dirty.current.present = true;
      setReady((v) => v + 1);
    };
    img.onerror = () => !stop && setLoadErr("عکس بارگذاری نشد.");
    img.src = p.src;
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.src, glErr]);

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
      if (l.type !== "image") continue;
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
  const neutral = p.tool === "persp" || p.tool === "spot";
  const showFull = p.tool === "crop" || p.tool === "straighten" || neutral;
  const gs: GeoState = neutral
    ? { turn: 0, straighten: 0, flipH: false, flipV: false, persp: null, crop: FULL }
    : { turn: p.state.turn, straighten: p.state.straighten, flipH: p.state.flipH, flipV: p.state.flipV, persp: p.state.persp, crop: p.state.crop };
  const geo = useMemo(
    () => new Geo(Wo, Ho, gs, showFull, box, view),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [Wo, Ho, gs.turn, gs.straighten, gs.flipH, gs.flipV, gs.persp, gs.crop.x, gs.crop.y, gs.crop.w, gs.crop.h, showFull, box, view],
  );
  geoRef.current = geo;

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
        eng.render(stateRef.current, { masks: pr.masks.map });
      } catch (e) {
        pr.onError((e as Error).message);
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
      eng.setSelection(SEL_TOOLS.has(pr.tool) ? pr.selection.canvas : null, pr.selection.ver);
      const M = mul(g.M, [1 / dpr, 0, 0, 0, 1 / dpr, 0, 0, 0, 1]);
      const splitPx = pr.compare === "split" ? g.tToScreen(g.frame.x0 + g.frame.w * splitRef.current, 0)[0] * dpr : -1;
      eng.present(M, [bw, bh], { before: pr.compare === "before", split: splitPx });
    }
  };
  const boxRef = useRef(box);
  boxRef.current = box;
  const splitRef = useRef(split);
  splitRef.current = split;

  useEffect(() => {
    dirty.current.render = true;
    schedule();
  }, [p.state.layers, p.state.adjust, p.state.curve, ready, tick, schedule, p.masks]);

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
    const ls = stateRef.current.layers;
    for (let i = ls.length - 1; i >= 0; i--) {
      const l = ls[i];
      if (!l.visible) continue;
      if (l.type === "base") continue;
      if (l.type !== "image" && l.type !== "text" && l.type !== "shape") continue;
      if (l.type === "text" && l.tile) continue;
      const sz = e.layerSize(l);
      if (!sz) continue;
      const c = corners(l, sz, Wo, Ho);
      if (c.length && lineIntersectionPoint(pt, c)) return l;
    }
    return null;
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
        if (act && act.visible && !act.locked) {
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
          p.setActiveId(hit.id);
          if (!hit.locked && "cx" in hit) beginDrag(e, { k: "move", id: hit.id, start: pt, c0: [hit.cx, hit.cy], moved: false });
          return;
        }
        if (inDoc) {
          const base = stateRef.current.layers.find((l) => l.type === "base");
          p.setActiveId(base?.id ?? null);
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
      case "wb":
        if (inDoc) p.onWb(pt[0], pt[1]);
        return;
      case "crop": {
        return; // با دستگیره‌های DOM
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
    if (p.tool === "brush" || p.tool === "clone" || p.tool === "heal") setCursor([sx, sy]);
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
        p.hist.end("برش");
        break;
      case "move":
        if (d.moved) p.hist.end("جابه‌جایی");
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

  const cursorDia = (p.opts.size * Wo) * geo.s * 2;
  const cursorStyle = p.tool === "hand" ? "grab" : ["brush", "clone", "heal", "spot", "gradient", "marquee", "ellipse", "lasso", "wb", "subject", "text"].includes(p.tool) ? "crosshair" : undefined;

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
      <canvas ref={canvas} className="pv-canvas" style={{ width: box.w, height: box.h }} data-testid="photo-canvas" />
      {glErr && <div className="vp-msg">{glErr}</div>}
      {loadErr && <div className="vp-msg">{loadErr}</div>}
      {!glErr && !loadErr && !ready && <div className="vp-msg">در حالِ بارگذاری…</div>}

      <svg className="pv-svg" width={box.w} height={box.h} aria-hidden="true">
        {grid && gridKind !== "off" && <GridLines kind={gridKind} fr={fr} />}
        {guides.x !== null && (() => { const a = sc([guides.x, 0]); const b = sc([guides.x, 1]); return <line className="pv-guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />; })()}
        {guides.y !== null && (() => { const a = sc([0, guides.y]); const b = sc([1, guides.y]); return <line className="pv-guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />; })()}
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
        {cursor && (p.tool === "brush" || p.tool === "clone" || p.tool === "heal") && <circle className="pv-cursor" cx={cursor[0]} cy={cursor[1]} r={Math.max(2, cursorDia / 2)} />}
      </svg>

      {p.tool === "crop" && (
        <div className="vp-crop" data-testid="crop-overlay">
          <i className="vp-shade" style={{ left: 0, top: 0, width: box.w, height: Math.max(0, cropR.y0) }} />
          <i className="vp-shade" style={{ left: 0, top: cropR.y1, width: box.w, height: Math.max(0, box.h - cropR.y1) }} />
          <i className="vp-shade" style={{ left: 0, top: cropR.y0, width: Math.max(0, cropR.x0), height: cropR.y1 - cropR.y0 }} />
          <i className="vp-shade" style={{ left: cropR.x1, top: cropR.y0, width: Math.max(0, box.w - cropR.x1), height: cropR.y1 - cropR.y0 }} />
          <div className="vp-crop-box" style={{ left: cropR.x0, top: cropR.y0, width: cropR.x1 - cropR.x0, height: cropR.y1 - cropR.y0 }} onPointerDown={(e) => beginCrop(e, "move")}>
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
