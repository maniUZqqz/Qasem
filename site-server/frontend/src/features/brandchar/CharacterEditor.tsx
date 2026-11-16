import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, ErrorBox, Input, Select, Spinner, fa } from "../../components/ui";
import { SHAPES, buildShape } from "../content/photo/pro/shapesLib";
import { Anchor, CharDoc, Character, Layer, LayerShape, Overview, PathPt, SvgOut, UnitPath, bcApi, isCancel } from "./api";
import { Chips, ColourField, Section, useNotice } from "./common";

/**
 * ویرایشگرِ شخصیتِ برند: بدنِ پارامتری (سبک‌ها و کتابخانه‌های بدن، چهره، مو، لباس، وسیله) که سرور به SVG می‌کشد + لایه‌های دستیِ برداری روی آن
 * (مستطیل، بیضی، خط، مسیرِ قلم با دستگیرهٔ بزیه، و کتابخانهٔ شکل‌های ادیتورِ عکس). لایه‌ها به سر/بدن/دست می‌چسبند و با ژست حرکت می‌کنند.
 * قرینه‌سازی، چسبیدن (شبکه، محور، لبهٔ لایه‌ها)، برگشت/جلو، رنگ از کیتِ برند. خروجیِ نهایی را همان موتورِ سرور می‌کشد (SVG، PNG، استیکر، برگهٔ مدل).
 */

type Mat = [number, number, number, number, number, number];
const IDENT: Mat = [1, 0, 0, 1, 0, 0];
const mapply = (m: Mat, x: number, y: number): [number, number] => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
function minv(m: Mat): Mat {
  const det = m[0] * m[3] - m[1] * m[2];
  if (Math.abs(det) < 1e-9) return IDENT;
  const a = m[3] / det, b = -m[1] / det, c = -m[2] / det, d = m[0] / det;
  return [a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5])];
}
const r2 = (v: number) => Math.round(v * 100) / 100;
const uid = () => "l" + Math.random().toString(36).slice(2, 8);
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/** مسیرِ واحد ⇒ d ِ SVG؛ همان قراردادِ backend/engine/vector.from_unit_path (جعبهٔ واحد، دستگیره = کسری از جعبه). */
export function pathD(p: UnitPath, w: number, h: number): string {
  const pts = p.pts;
  if (pts.length < 2) return "";
  const P = (x: number, y: number) => `${r2((x - 0.5) * w)} ${r2((y - 0.5) * h)}`;
  let d = `M${P(pts[0].x, pts[0].y)}`;
  const closed = p.closed && pts.length > 2;
  const segs = closed ? pts.length : pts.length - 1;
  for (let i = 0; i < segs; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    if (!a.ho && !b.hi) {
      if (!(i === segs - 1 && closed)) d += ` L${P(b.x, b.y)}`;
      continue;
    }
    d += ` C${P(a.x + (a.ho ? a.ho[0] : 0), a.y + (a.ho ? a.ho[1] : 0))} ${P(b.x + (b.hi ? b.hi[0] : 0), b.y + (b.hi ? b.hi[1] : 0))} ${P(b.x, b.y)}`;
  }
  return closed ? d + " Z" : d;
}

function layerShape(l: Layer): JSX.Element | null {
  const { w, h } = l.box;
  const common = { fill: l.shape === "line" ? "none" : l.fill ?? "none", stroke: l.stroke ?? (l.shape === "line" ? l.fill ?? "#000" : "none"), strokeWidth: l.sw || (l.shape === "line" ? 6 : 0), opacity: l.opacity, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (l.shape === "rect") return <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={l.radius} {...common} />;
  if (l.shape === "ellipse") return <ellipse cx={0} cy={0} rx={w / 2} ry={h / 2} {...common} />;
  if (l.shape === "line") return <line x1={-w / 2} y1={0} x2={w / 2} y2={0} {...common} />;
  if (l.path) return <path d={pathD(l.path, w, h)} {...common} />;
  return null;
}

function layerTransform(l: Layer): string {
  return `translate(${l.box.cx} ${l.box.cy}) rotate(${l.box.rot})${l.flip_x ? " scale(-1 1)" : ""}`;
}

const matStr = (m: Mat) => `matrix(${m.join(" ")})`;

type Tool = "select" | "rect" | "ellipse" | "line" | "pen" | `shape:${string}`;
type Drag = { kind: "move" | "resize" | "rotate" | "create"; id?: string; sx: number; sy: number; start?: Layer; startDoc: CharDoc; tool?: Tool; anchor: Anchor; moved: boolean; handle?: string } | null;

const AXIS: Record<Anchor, number> = { world: 300, head: 0, body: 0, hand: 0 };
const HIST_MAX = 100;
const THRESH = 6;

type Pen = { pts: PathPt[]; anchor: Anchor; dragging: boolean } | null;

export default function CharacterEditor({ id, ch, ov, onSaved, onReload }: { id: string; ch: Character; ov: Overview; onSaved: (c: Character) => void; onReload: () => Promise<void> }) {
  const nav = useNavigate();
  const [doc, setDoc] = useState<CharDoc>(ch.doc);
  const hist = useRef<{ past: CharDoc[]; future: CharDoc[] }>({ past: [], future: [] });
  const [, bump] = useState(0);
  const [pose, setPose] = useState("stand");
  const [expression, setExpression] = useState("happy");
  const [flip, setFlip] = useState(false);
  const [base, setBase] = useState<SvgOut | null>(null);
  const [baseBusy, setBaseBusy] = useState(false);
  const [baseError, setBaseError] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [selId, setSelId] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Anchor>("world");
  const [sym, setSym] = useState(false);
  const [snap, setSnap] = useState(true);
  const [grid, setGrid] = useState(false);
  const [panel, setPanel] = useState<"look" | "face" | "hair" | "outfit" | "prop" | "colour" | "layers">("look");
  const [guides, setGuides] = useState<{ x?: number; y?: number }[]>([]);
  const [pen, setPen] = useState<Pen>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [finalPrev, setFinalPrev] = useState<string | null>(null);
  const n = useNotice();
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag>(null);
  const docRef = useRef(doc);
  docRef.current = doc;

  const locked = ch.locked;
  const vector = doc.style !== "stick";
  const swatches = useMemo(() => {
    const out: string[] = [];
    for (const c of [...ov.store.colors, ...ch.brand_colours, ...ch.palette.map((p) => p.hex)]) if (c && !out.includes(c.toLowerCase())) out.push(c.toLowerCase());
    return out.slice(0, 10);
  }, [ov.store.colors, ch.brand_colours, ch.palette]);

  // با عوضِ شخصیت یا ذخیره/بازگردانی: سند از نو
  const chKey = JSON.stringify([ch.id, ch.version, ch.locked, ch.doc]);
  useEffect(() => {
    docRef.current = ch.doc;
    setDoc(ch.doc);
    hist.current = { past: [], future: [] };
    bump((n) => n + 1);
    setSelId(null);
    setPen(null);
  }, [chKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(doc) !== JSON.stringify(ch.doc);
  const sel = doc.layers.find((l) => l.id === selId) ?? null;

  // ───────────── تاریخچه
  const commit = useCallback((next: CharDoc, from?: CharDoc) => {
    const prev = from ?? docRef.current;
    if (JSON.stringify(prev) === JSON.stringify(next)) return;
    hist.current = { past: [...hist.current.past.slice(-(HIST_MAX - 1)), prev], future: [] };
    docRef.current = next;
    setDoc(next);
    bump((n) => n + 1);
  }, []);
  const undo = useCallback(() => {
    const h = hist.current;
    if (!h.past.length) return;
    const prev = h.past[h.past.length - 1];
    hist.current = { past: h.past.slice(0, -1), future: [docRef.current, ...h.future].slice(0, HIST_MAX) };
    docRef.current = prev;
    setDoc(prev);
    bump((n) => n + 1);
  }, []);
  const redo = useCallback(() => {
    const h = hist.current;
    if (!h.future.length) return;
    const nxt = h.future[0];
    hist.current = { past: [...h.past.slice(-(HIST_MAX - 1)), docRef.current], future: h.future.slice(1) };
    docRef.current = nxt;
    setDoc(nxt);
    bump((n) => n + 1);
  }, []);

  // ───────────── بدنِ پارامتری (SVG از سرور؛ لایه‌های دستی را خودمان می‌کشیم)
  const baseKey = useMemo(() => JSON.stringify([{ ...doc, layers: [], name: "" }, pose, expression, flip, ch.id]), [doc, pose, expression, flip, ch.id]);
  useEffect(() => {
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      setBaseBusy(true);
      bcApi
        .svg(id, ch.id, { pose, expression, flip, view: "canvas", doc: { ...docRef.current, layers: [] } }, ctl.signal)
        .then((r) => {
          setBase(r);
          setBaseError(null);
        })
        .catch((e) => {
          if (!isCancel(e)) setBaseError(errorMessage(e));
        })
        .finally(() => setBaseBusy(false));
    }, 160);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [baseKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // پیش‌نمایشِ نهایی (پست با پس‌زمینه) — کندتر و جدا
  useEffect(() => {
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      bcApi
        .preview(id, ch.id, { size: "ig_square", pose, expression, flip, background: "brand", doc: docRef.current }, ctl.signal)
        .then((r) => setFinalPrev(r.image))
        .catch(() => undefined);
    }, 700);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [JSON.stringify(doc), pose, expression, flip, ch.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const baseInner = useMemo(() => {
    if (!base) return "";
    const m = base.svg.match(/<svg[^>]*>([\s\S]*)<\/svg>\s*$/);
    return m ? m[1] : "";
  }, [base]);
  const anchors = useMemo(() => {
    const a = base?.anchors;
    const get = (k: Anchor): Mat => (a && a[k] && a[k].length === 6 ? (a[k] as Mat) : IDENT);
    return { world: get("world"), head: get("head"), body: get("body"), hand: get("hand") } as Record<Anchor, Mat>;
  }, [base]);
  const vb = base && base.view && base.view.length === 4 ? base.view : [0, 0, 600, 900];

  // ───────────── نقطه‌ها
  const toLocal = (e: { clientX: number; clientY: number }, a: Anchor): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const ctm = svg.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return mapply(minv(anchors[a]), p.x, p.y);
  };

  const snapPt = (x: number, y: number, a: Anchor, skip?: string, box?: { w: number; h: number }): { x: number; y: number; gs: { x?: number; y?: number }[] } => {
    if (!snap) return { x, y, gs: [] };
    const gs: { x?: number; y?: number }[] = [];
    const xs: number[] = [AXIS[a]];
    const ys: number[] = [];
    for (const l of docRef.current.layers) {
      if (l.id === skip || l.anchor !== a || l.hidden) continue;
      xs.push(l.box.cx, l.box.cx - l.box.w / 2, l.box.cx + l.box.w / 2);
      ys.push(l.box.cy, l.box.cy - l.box.h / 2, l.box.cy + l.box.h / 2);
    }
    let bx = x;
    let by = y;
    const offs = box ? [0, -box.w / 2, box.w / 2] : [0];
    const offsY = box ? [0, -box.h / 2, box.h / 2] : [0];
    let bestX = THRESH + 1;
    for (const c of xs) for (const o of offs) if (Math.abs(x + o - c) < bestX) { bestX = Math.abs(x + o - c); bx = c - o; }
    let bestY = THRESH + 1;
    for (const c of ys) for (const o of offsY) if (Math.abs(y + o - c) < bestY) { bestY = Math.abs(y + o - c); by = c - o; }
    if (bestX <= THRESH) gs.push({ x: bx + (box ? 0 : 0) });
    else if (grid) bx = Math.round(x / 10) * 10;
    if (bestY <= THRESH) gs.push({ y: by });
    else if (grid) by = Math.round(y / 10) * 10;
    return { x: bx, y: by, gs };
  };

  // ───────────── لایه‌ها: ساخت، ویرایش، قرینه
  const mirrorOf = (l: Layer): Layer => ({ ...l, id: l.link || uid(), box: { ...l.box, cx: 2 * AXIS[l.anchor] - l.box.cx, rot: -l.box.rot }, flip_x: !l.flip_x, link: l.id, name: l.name ? `${l.name} ◂▸` : "" });
  const withTwin = (d: CharDoc, l: Layer): CharDoc => {
    if (!sym) return d;
    const twinId = l.link && d.layers.find((x) => x.id === l.link) ? l.link : null;
    if (Math.abs(l.box.cx - AXIS[l.anchor]) < 0.5 && !twinId) return d;
    const tw = mirrorOf({ ...l, link: twinId ?? "" });
    const layers = d.layers.map((x) => (x.id === l.id ? { ...x, link: tw.id } : x));
    const idx = layers.findIndex((x) => x.id === tw.id);
    if (idx >= 0) layers[idx] = { ...tw, id: layers[idx].id };
    else layers.push(tw);
    return { ...d, layers };
  };
  const upd = (lid: string, patch: Partial<Layer> | ((l: Layer) => Partial<Layer>), opts?: { live?: boolean; from?: CharDoc }): CharDoc => {
    const cur = docRef.current;
    const layers = cur.layers.map((l) => (l.id === lid ? { ...l, ...(typeof patch === "function" ? patch(l) : patch) } : l));
    let next: CharDoc = { ...cur, layers };
    const l2 = layers.find((l) => l.id === lid);
    if (l2) next = withTwin(next, l2);
    if (opts?.live) {
      docRef.current = next;
      setDoc(next);
    }
    else commit(next, opts?.from);
    return next;
  };
  const addLayer = (l: Layer) => {
    if (docRef.current.layers.length >= ov.options.limits.max_layers) {
      n.fail(new Error(`حداکثر ${fa(ov.options.limits.max_layers)} لایه`));
      return;
    }
    let next: CharDoc = { ...docRef.current, layers: [...docRef.current.layers, l] };
    next = withTwin(next, l);
    commit(next);
    setSelId(l.id);
  };
  const newLayer = (shape: LayerShape, cx: number, cy: number, w: number, h: number, extra?: Partial<Layer>): Layer => ({
    id: uid(), name: "", shape, anchor, box: { cx: r2(cx), cy: r2(cy), w: Math.max(2, r2(w)), h: Math.max(2, r2(h)), rot: 0 }, fill: shape === "line" ? null : doc.top, stroke: shape === "line" ? doc.outline : null,
    sw: shape === "line" ? 6 : 0, opacity: 1, above: true, hidden: false, locked: false, radius: 0, flip_x: false, link: "", shape_id: "", ...extra,
  });
  const removeLayer = (lid: string) => {
    const l = docRef.current.layers.find((x) => x.id === lid);
    if (!l) return;
    commit({ ...docRef.current, layers: docRef.current.layers.filter((x) => x.id !== lid && x.id !== l.link && x.link !== lid) });
    setSelId(null);
  };
  const moveZ = (lid: string, dir: -1 | 1) => {
    const arr = [...docRef.current.layers];
    const i = arr.findIndex((x) => x.id === lid);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    commit({ ...docRef.current, layers: arr });
  };
  const changeAnchor = (l: Layer, to: Anchor) => {
    const [wx, wy] = mapply(anchors[l.anchor], l.box.cx, l.box.cy);
    const [lx, ly] = mapply(minv(anchors[to]), wx, wy);
    upd(l.id, { anchor: to, box: { ...l.box, cx: r2(lx), cy: r2(ly) } });
  };

  // ───────────── اشاره‌گر
  const onDown = (e: RPointerEvent<SVGSVGElement>) => {
    if (locked || !vector || e.button > 0) return;
    const target = (e.target as Element).closest("[data-lid]") as HTMLElement | null;
    const [px, py] = toLocal(e, tool === "pen" && pen ? pen.anchor : anchor);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    if (tool === "pen") {
      const a = pen ? pen.anchor : anchor;
      const [x, y] = toLocal(e, a);
      const pts = pen ? [...pen.pts] : [];
      if (pts.length > 2 && Math.hypot(pts[0].x - x, pts[0].y - y) < 10) {
        finishPen(true);
        return;
      }
      pts.push({ x, y, hi: null, ho: null });
      setPen({ pts, anchor: a, dragging: true });
      return;
    }
    if (tool === "select") {
      const hid = (e.target as Element).getAttribute("data-handle");
      if (hid && sel) {
        drag.current = { kind: hid === "rot" ? "rotate" : "resize", id: sel.id, sx: px, sy: py, start: sel, startDoc: docRef.current, anchor: sel.anchor, moved: false, handle: hid };
        return;
      }
      if (target?.dataset.lid) {
        const l = docRef.current.layers.find((x) => x.id === target.dataset.lid);
        if (l) {
          setSelId(l.id);
          if (!l.locked) {
            const [lx, ly] = toLocal(e, l.anchor);
            drag.current = { kind: "move", id: l.id, sx: lx, sy: ly, start: l, startDoc: docRef.current, anchor: l.anchor, moved: false };
          }
          return;
        }
      }
      setSelId(null);
      return;
    }
    // ابزارهای ساخت
    const s = snapPt(px, py, anchor);
    drag.current = { kind: "create", sx: s.x, sy: s.y, startDoc: docRef.current, tool, anchor, moved: false };
    setGuides(s.gs);
    const l = tool === "rect" || tool === "ellipse" || tool === "line" ? newLayer(tool, s.x, s.y, 2, tool === "line" ? 2 : 2) : tool.startsWith("shape:") ? shapeLayer(tool.slice(6), s.x, s.y, 2) : null;
    if (l) {
      drag.current.id = l.id;
      const withNew = { ...docRef.current, layers: [...docRef.current.layers, l] };
      docRef.current = withNew;
      setDoc(withNew);
      setSelId(l.id);
    }
  };

  const shapeLayer = (sid: string, cx: number, cy: number, w: number): Layer | null => {
    const b = buildShape(sid);
    if (!b) return null;
    const pts: PathPt[] = b.path.pts.map((p) => ({ x: p.x, y: p.y, hi: p.hi, ho: p.ho }));
    return newLayer("path", cx, cy, w, w * b.aspect, { path: { closed: true, pts }, shape_id: sid, name: SHAPES.find((s) => s.id === sid)?.title ?? "" });
  };

  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (pen && pen.dragging && pen.pts.length) {
      const [x, y] = toLocal(e, pen.anchor);
      const last = pen.pts[pen.pts.length - 1];
      const dx = x - last.x;
      const dy = y - last.y;
      if (Math.hypot(dx, dy) > 4) {
        const pts = pen.pts.slice(0, -1);
        pts.push({ ...last, ho: [dx, dy], hi: [-dx, -dy] });
        setPen({ ...pen, pts });
      }
      return;
    }
    const d = drag.current;
    if (!d || !d.id) return;
    const [px, py] = toLocal(e, d.anchor);
    d.moved = true;
    if (d.kind === "move" && d.start) {
      const s = snapPt(d.start.box.cx + (px - d.sx), d.start.box.cy + (py - d.sy), d.anchor, d.id, { w: d.start.box.w, h: d.start.box.h });
      setGuides(s.gs);
      upd(d.id, { box: { ...d.start.box, cx: r2(s.x), cy: r2(s.y) } }, { live: true });
    } else if (d.kind === "create") {
      const s = snapPt(px, py, d.anchor);
      setGuides(s.gs);
      const w = Math.abs(s.x - d.sx);
      const h = Math.abs(s.y - d.sy);
      const t = d.tool ?? "rect";
      const cx = (s.x + d.sx) / 2;
      const cy = (s.y + d.sy) / 2;
      if (t === "line") upd(d.id, (l) => ({ box: { ...l.box, cx: r2(cx), cy: r2(cy), w: Math.max(2, r2(Math.hypot(s.x - d.sx, s.y - d.sy))), h: 2, rot: r2((Math.atan2(s.y - d.sy, s.x - d.sx) * 180) / Math.PI) } }), { live: true });
      else if (typeof t === "string" && t.startsWith("shape:")) {
        const b = buildShape(t.slice(6));
        const ww = Math.max(4, Math.max(w, h / (b?.aspect || 1)));
        upd(d.id, (l) => ({ box: { ...l.box, cx: r2(d.sx + (s.x >= d.sx ? ww / 2 : -ww / 2)), cy: r2(d.sy + (s.y >= d.sy ? (ww * (b?.aspect || 1)) / 2 : -(ww * (b?.aspect || 1)) / 2)), w: r2(ww), h: r2(ww * (b?.aspect || 1)) } }), { live: true });
      } else upd(d.id, (l) => ({ box: { ...l.box, cx: r2(cx), cy: r2(cy), w: Math.max(2, r2(w)), h: Math.max(2, r2(h)) } }), { live: true });
    } else if (d.kind === "resize" && d.start) {
      const st = d.start;
      const dx = px - st.box.cx;
      const dy = py - st.box.cy;
      const rad = (-st.box.rot * Math.PI) / 180;
      const lx = dx * Math.cos(rad) - dy * Math.sin(rad);
      const ly = dx * Math.sin(rad) + dy * Math.cos(rad);
      const keep = e.shiftKey && st.box.w > 0 && st.box.h > 0;
      let w = Math.max(4, Math.abs(lx) * 2);
      let h = Math.max(4, Math.abs(ly) * 2);
      if (keep) h = w * (st.box.h / st.box.w);
      if (st.shape === "line") h = st.box.h;
      upd(d.id, { box: { ...st.box, w: r2(w), h: r2(h) } }, { live: true });
    } else if (d.kind === "rotate" && d.start) {
      const st = d.start;
      let rot = (Math.atan2(py - st.box.cy, px - st.box.cx) * 180) / Math.PI + 90;
      if (e.shiftKey || snap) rot = Math.round(rot / 15) * 15;
      upd(d.id, { box: { ...st.box, rot: r2(((rot + 540) % 360) - 180) } }, { live: true });
    }
  };

  const onUp = () => {
    if (pen) {
      setPen({ ...pen, dragging: false });
      return;
    }
    const d = drag.current;
    drag.current = null;
    setGuides([]);
    if (!d) return;
    if (d.kind === "create" && d.id) {
      let cur = docRef.current;
      const l = cur.layers.find((x) => x.id === d.id);
      if (l && !d.moved) {                              // کلیکِ ساده ⇒ اندازهٔ پیش‌فرض
        const big = l.shape === "line" ? 120 : l.shape === "path" ? 90 : 80;
        const b = l.shape_id ? buildShape(l.shape_id) : null;
        cur = { ...cur, layers: cur.layers.map((x) => (x.id === d.id ? { ...x, box: { ...x.box, w: big, h: l.shape === "line" ? 2 : l.shape === "path" ? big * (b?.aspect || 1) : big } } : x)) };
      }
      const fin = l ? withTwin(cur, cur.layers.find((x) => x.id === d.id) ?? l) : cur;
      commit(fin, d.startDoc);
      setTool("select");
      return;
    }
    if (d.moved && d.id) {
      commit(docRef.current, d.startDoc);
    }
  };

  const finishPen = (closed: boolean) => {
    if (!pen || pen.pts.length < 2) {
      setPen(null);
      return;
    }
    const pts = pen.pts;
    const xs: number[] = [];
    const ys: number[] = [];
    for (const p of pts) {
      xs.push(p.x, ...(p.ho ? [p.x + p.ho[0]] : []), ...(p.hi ? [p.x + p.hi[0]] : []));
      ys.push(p.y, ...(p.ho ? [p.y + p.ho[1]] : []), ...(p.hi ? [p.y + p.hi[1]] : []));
    }
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const w = Math.max(4, x1 - x0);
    const h = Math.max(4, y1 - y0);
    const unit: UnitPath = {
      closed: closed && pts.length > 2,
      pts: pts.map((p) => ({ x: r2((p.x - (x0 + x1) / 2) / w + 0.5), y: r2((p.y - (y0 + y1) / 2) / h + 0.5), hi: p.hi ? [r2(p.hi[0] / w), r2(p.hi[1] / h)] : null, ho: p.ho ? [r2(p.ho[0] / w), r2(p.ho[1] / h)] : null })),
    };
    const l = newLayer("path", (x0 + x1) / 2, (y0 + y1) / 2, w, h, { anchor: pen.anchor, path: unit, name: "مسیر", fill: unit.closed ? doc.top : null, stroke: unit.closed ? null : doc.outline, sw: unit.closed ? 0 : 6 });
    setPen(null);
    addLayer(l);
    setTool("select");
  };

  // ───────────── صفحه‌کلید
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); return; }
      if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); redo(); return; }
      if (e.key === "Escape") { setPen(null); setTool("select"); return; }
      if (e.key === "Enter" && pen) { e.preventDefault(); finishPen(false); return; }
      if (locked) return;
      const l = docRef.current.layers.find((x) => x.id === selId);
      if (!l) return;
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeLayer(l.id); return; }
      const step = e.shiftKey ? 10 : 1;
      const mv: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (mv[e.key] && !l.locked) { e.preventDefault(); upd(l.id, { box: { ...l.box, cx: r2(l.box.cx + mv[e.key][0]), cy: r2(l.box.cy + mv[e.key][1]) } }); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  // ───────────── اقدام‌ها
  const setD = <K extends keyof CharDoc>(k: K, v: CharDoc[K]) => commit({ ...docRef.current, [k]: v });
  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try {
      await fn();
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };
  const save = () => run("save", async () => {
    const c = await bcApi.patch(id, ch.id, { doc });
    onSaved(c);
    n.ok("ذخیره شد.");
  });
  const lockIt = () => run("lock", async () => {
    if (dirty) await bcApi.patch(id, ch.id, { doc });
    const c = await bcApi.lock(id, ch.id);
    onSaved(c);
    await onReload();
    n.ok(`ظاهر تأیید شد (نسخهٔ ${fa(c.version)}). از این به بعد همهٔ خروجی‌ها از همین نسخه‌اند.`);
  });
  const unlockIt = () => run("unlock", async () => {
    onSaved(await bcApi.unlock(id, ch.id));
    n.ok("قفل باز شد.");
  });
  const checkIt = () => run("check", async () => {
    if (dirty) await bcApi.patch(id, ch.id, { doc });
    const r = await bcApi.check(id, ch.id);
    await onReload();
    n.ok(r.ok ? `بررسیِ ثبات: همهٔ ${fa(r.total ?? 0)} تصویر قبول (ژست‌ها × اندازه‌ها).` : `بررسیِ ثبات: ${fa((r.failed ?? []).length)} مورد رد شد.`);
  });
  const toPhotoEditor = () => run("photo", async () => {
    if (dirty) await bcApi.patch(id, ch.id, { doc });
    const r = await bcApi.sticker(id, ch.id, { pose, expression, flip, crop: "full" });
    if (r.asset) nav(`/stores/${id}/photo-editor?asset=${r.asset.id}&mode=manual`);
  });

  const choices = ov.options.choices;
  const L = ov.options.limits;
  const colourFields: [keyof CharDoc, string][] = [["skin", "پوست"], ["hair_colour", "مو"], ["top", "لباسِ اصلی"], ["top2", "رنگِ دومِ لباس"], ["bottom", "شلوار"], ["shoes", "کفش"], ["hat_colour", "کلاه"], ["neck_colour", "شال/کراوات"], ["extra_colour", "وسیلهٔ اضافه"], ["prop_colour", "وسیلهٔ دست"], ["outline", "خطِ دور"]];
  const below = doc.layers.filter((l) => !l.above);
  const above = doc.layers.filter((l) => l.above);

  const renderLayer = (l: Layer) => {
    if (l.hidden) return null;
    return (
      <g key={l.id} transform={matStr(anchors[l.anchor])}>
        <g data-lid={l.id} transform={layerTransform(l)} style={{ cursor: tool === "select" && !l.locked ? "move" : "default" }}>
          {layerShape(l)}
        </g>
      </g>
    );
  };

  const selBox = sel && !sel.hidden ? sel : null;
  const handles = selBox
    ? (() => {
        const hw = selBox.box.w / 2;
        const hh = selBox.shape === "line" ? 0 : selBox.box.h / 2;
        const pts: [string, number, number][] = [["br", hw, hh], ["bl", -hw, hh], ["tr", hw, -hh], ["tl", -hw, -hh]];
        return pts;
      })()
    : [];

  const penD = useMemo(() => {
    if (!pen || pen.pts.length < 1) return "";
    const pts = pen.pts;
    let d = `M${pts[0].x} ${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1];
      const b = pts[i];
      d += a.ho || b.hi ? ` C${a.x + (a.ho?.[0] ?? 0)} ${a.y + (a.ho?.[1] ?? 0)} ${b.x + (b.hi?.[0] ?? 0)} ${b.y + (b.hi?.[1] ?? 0)} ${b.x} ${b.y}` : ` L${b.x} ${b.y}`;
    }
    return d;
  }, [pen]);

  const toolBtn = (t: Tool, label: string) => (
    <button key={t} type="button" className="bce-tool" aria-pressed={tool === t} disabled={locked || !vector} onClick={() => { setTool(t); setPen(null); }} title={label}>
      {label}
    </button>
  );

  return (
    <div className="bce" data-testid="character-editor">
      <div className="bce-stage">
        <div className="bce-bar" role="toolbar" aria-label="ابزارهای ویرایشگر">
          <button type="button" className="bce-tool" onClick={undo} disabled={!hist.current.past.length || locked} title="برگشت (Ctrl+Z)" aria-label="برگشت">↶ برگشت</button>
          <button type="button" className="bce-tool" onClick={redo} disabled={!hist.current.future.length || locked} title="جلو (Ctrl+Y)" aria-label="جلو">↷ جلو</button>
          <span className="sep" />
          {toolBtn("select", "انتخاب")}
          {toolBtn("rect", "مستطیل")}
          {toolBtn("ellipse", "بیضی")}
          {toolBtn("line", "خط")}
          {toolBtn("pen", "قلم")}
          <span className="sep" />
          <button type="button" className="bce-tool" aria-pressed={sym} onClick={() => setSym((v) => !v)} disabled={locked || !vector} title="قرینه‌سازی نسبت به محورِ وسط">⇋ قرینه</button>
          <button type="button" className="bce-tool" aria-pressed={snap} onClick={() => setSnap((v) => !v)} disabled={!vector} title="چسبیدن به محور و لبهٔ لایه‌ها">⌖ چسبیدن</button>
          <button type="button" className="bce-tool" aria-pressed={grid} onClick={() => setGrid((v) => !v)} disabled={!vector} title="شبکهٔ ۱۰ واحدی">▦ شبکه</button>
          <span className="sep" />
          <label className="bc-row" style={{ gap: 4, fontSize: 12 }}>
            جایگیری
            <Select style={{ minWidth: 130 }} value={anchor} disabled={locked || !vector} onChange={(e) => setAnchor(e.target.value as Anchor)} aria-label="جایگیریِ لایهٔ تازه">
              {ov.options.anchors.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.fa}
                </option>
              ))}
            </Select>
          </label>
        </div>

        <div className="bce-bar">
          <label className="bc-row" style={{ gap: 4, fontSize: 12 }}>
            ژست
            <Select style={{ minWidth: 150 }} value={pose} onChange={(e) => setPose(e.target.value)} aria-label="ژست">
              {ov.options.poses.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.fa}
                </option>
              ))}
            </Select>
          </label>
          <label className="bc-row" style={{ gap: 4, fontSize: 12 }}>
            حالت
            <Select style={{ minWidth: 110 }} value={expression} onChange={(e) => setExpression(e.target.value)} aria-label="حالتِ چهره">
              {ov.options.expressions.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.fa}
                </option>
              ))}
            </Select>
          </label>
          <button type="button" className="bce-tool" aria-pressed={flip} onClick={() => setFlip((v) => !v)}>↔ آینه</button>
          {baseBusy ? <Spinner size={16} /> : null}
          <span style={{ flex: 1 }} />
          {dirty ? <Badge tone="warn">ذخیره‌نشده</Badge> : <Badge tone="ok">ذخیره‌شده</Badge>}
        </div>

        {baseError ? <ErrorBox message={baseError} /> : null}
        <div className="bce-canvas" data-testid="editor-canvas">
          <svg
            ref={svgRef}
            viewBox={`${vb[0]} ${vb[1]} ${vb[2]} ${vb[3]}`}
            role="img"
            aria-label="بومِ ویرایشِ شخصیت"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onDoubleClick={() => { if (pen) finishPen(false); }}
            style={{ cursor: locked ? "not-allowed" : tool === "select" ? "default" : "crosshair" }}
          >
            {grid ? (
              <g stroke="currentColor" strokeOpacity={0.12} strokeWidth={0.6} pointerEvents="none">
                {Array.from({ length: Math.floor(vb[2] / 50) + 1 }, (_, i) => <line key={`gx${i}`} x1={vb[0] + i * 50} y1={vb[1]} x2={vb[0] + i * 50} y2={vb[1] + vb[3]} />)}
                {Array.from({ length: Math.floor(vb[3] / 50) + 1 }, (_, i) => <line key={`gy${i}`} x1={vb[0]} y1={vb[1] + i * 50} x2={vb[0] + vb[2]} y2={vb[1] + i * 50} />)}
              </g>
            ) : null}
            {vector ? below.map(renderLayer) : null}
            <g pointerEvents="none" dangerouslySetInnerHTML={{ __html: baseInner }} />
            {vector ? above.map(renderLayer) : null}
            {vector ? <line x1={AXIS.world} y1={vb[1]} x2={AXIS.world} y2={vb[1] + vb[3]} stroke="var(--brand, #126f85)" strokeOpacity={sym ? 0.5 : 0.18} strokeDasharray="6 6" pointerEvents="none" /> : null}
            {guides.map((g, i) => (
              <line key={i} {...(g.x !== undefined ? { x1: mapply(anchors[anchor], g.x, 0)[0], x2: mapply(anchors[anchor], g.x, 0)[0], y1: vb[1], y2: vb[1] + vb[3] } : { y1: mapply(anchors[anchor], 0, g.y ?? 0)[1], y2: mapply(anchors[anchor], 0, g.y ?? 0)[1], x1: vb[0], x2: vb[0] + vb[2] })} stroke="#e0568f" strokeWidth={1.2} pointerEvents="none" />
            ))}
            {selBox && !locked ? (
              <g transform={matStr(anchors[selBox.anchor])}>
                <g transform={`translate(${selBox.box.cx} ${selBox.box.cy}) rotate(${selBox.box.rot})`}>
                  {selBox.shape !== "line" ? <rect x={-selBox.box.w / 2} y={-selBox.box.h / 2} width={selBox.box.w} height={selBox.box.h} fill="none" stroke="var(--brand, #126f85)" strokeDasharray="5 4" pointerEvents="none" /> : null}
                  {handles.map(([k, x, y]) => <rect key={k} className="bce-handle" data-handle={k} x={x - 6} y={y - 6} width={12} height={12} rx={3} style={{ cursor: "nwse-resize" }} />)}
                  <line x1={0} y1={-(selBox.shape === "line" ? 0 : selBox.box.h / 2)} x2={0} y2={-(selBox.shape === "line" ? 0 : selBox.box.h / 2) - 24} stroke="var(--brand, #126f85)" pointerEvents="none" />
                  <circle className="bce-handle" data-handle="rot" cx={0} cy={-(selBox.shape === "line" ? 0 : selBox.box.h / 2) - 24} r={7} style={{ cursor: "grab" }} />
                </g>
              </g>
            ) : null}
            {pen ? (
              <g transform={matStr(anchors[pen.anchor])} pointerEvents="none">
                <path d={penD} fill="none" stroke="#e0568f" strokeWidth={2} />
                {pen.pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={4} fill={i === 0 ? "#e0568f" : "#fff"} stroke="#e0568f" />)}
              </g>
            ) : null}
          </svg>
        </div>
        <p className="bce-hint">
          {locked
            ? "ظاهر قفل است؛ برای ویرایش، «بازکردنِ قفل» را بزنید."
            : !vector
              ? "سبکِ «آدمک‌چوبی» از موتورِ ماسکوت کشیده می‌شود؛ لایه‌های دستی فقط برای سبک‌های برداری است. گزینه‌های بدن و رنگ‌ها همچنان کار می‌کنند."
              : tool === "pen"
                ? "قلم: برای هر نقطه کلیک کنید؛ کشیدن بعد از کلیک دستگیرهٔ منحنی می‌سازد. Enter یا دابل‌کلیک = پایانِ مسیر؛ کلیک روی نقطهٔ اول = بستن."
                : "یک ابزار بردارید و روی بوم بکشید. لایه‌ای که به «سر» می‌چسبد با ژست‌ها حرکت می‌کند. Delete = حذف؛ فلش‌ها = جابه‌جایی؛ Shift = اندازهٔ هم‌نسبت."}
        </p>
        {n.error ? <ErrorBox message={n.error} /> : null}
        {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}
        <div className="bc-row">
          <Button type="button" onClick={() => void save()} disabled={busy !== null || locked || !dirty}>{busy === "save" ? <Spinner size={14} /> : null} ذخیره</Button>
          {locked ? <Button type="button" variant="secondary" onClick={() => void unlockIt()} disabled={busy !== null}>بازکردنِ قفل</Button> : <Button type="button" variant="secondary" onClick={() => void lockIt()} disabled={busy !== null}>تأییدِ ظاهر (قفل)</Button>}
          <Button type="button" variant="ghost" onClick={() => void checkIt()} disabled={busy !== null}>{busy === "check" ? <Spinner size={14} /> : null} بررسیِ ثبات (همهٔ ژست‌ها × اندازه‌ها)</Button>
          <Button type="button" variant="ghost" onClick={() => void toPhotoEditor()} disabled={busy !== null}>ویرایش در ادیتورِ عکس</Button>
          {ch.check.at ? <Badge tone={ch.check.ok ? "ok" : "bad"}>{ch.check.ok ? `ثبات ✓ ${fa(ch.check.passed ?? 0)}/${fa(ch.check.total ?? 0)}` : `ثبات: ${fa((ch.check.failed ?? []).length)} مورد رد`}</Badge> : null}
        </div>
      </div>

      <div className="bce-side">
        <div className="bce-tabs" role="tablist" aria-label="کتابخانه‌ها">
          {([["look", "سبک و بدن"], ["face", "چهره"], ["hair", "مو و کلاه"], ["outfit", "لباس"], ["prop", "وسیله"], ["colour", "رنگ‌ها"], ["layers", `لایه‌ها (${fa(doc.layers.length)})`]] as const).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={panel === k} className="bc-chip" aria-pressed={panel === k} onClick={() => setPanel(k)}>{label}</button>
          ))}
        </div>

        {panel === "look" ? (
          <Section title="سبکِ کشیدن و بدن" hint="سه سبکِ برداری + آدمک‌چوبیِ ماسکوت؛ هر سبک همان ژست‌ها و همان شخصیت را می‌کشد.">
            <span className="bc-sub">سبک</span>
            <div className="bc-chips">
              {ov.options.styles.map((s) => (
                <button key={s.key} type="button" className="bc-chip" aria-pressed={doc.style === s.key} disabled={locked} title={s.hint} onClick={() => setD("style", s.key)}>{s.fa}</button>
              ))}
            </div>
            <p className="bc-muted">{ov.options.styles.find((s) => s.key === doc.style)?.hint}</p>
            <span className="bc-sub">بدن</span>
            <Chips options={choices.body} value={doc.body} disabled={locked} onChange={(v) => setD("body", v)} label="بدن" />
            <span className="bc-sub">شکلِ سر</span>
            <Chips options={choices.head_style} value={doc.head_style} disabled={locked} onChange={(v) => setD("head_style", v)} label="شکلِ سر" />
            <span className="bc-sub">رنگِ پوست</span>
            <div className="bc-swatches">
              {ov.options.skin_presets.map((s) => <button key={s.hex} type="button" disabled={locked} className="bc-swatch" style={{ background: s.hex, outline: doc.skin === s.hex ? "2px solid var(--brand)" : undefined }} title={s.fa} aria-label={`پوستِ ${s.fa}`} onClick={() => setD("skin", s.hex)} />)}
            </div>
            <label className="bc-row" style={{ gap: 6 }}>
              <input type="checkbox" disabled={locked || !ch.has_logo && !ov.store.has_logo} checked={doc.logo === "chest"} onChange={(e) => setD("logo", e.target.checked ? "chest" : "none")} /> لوگوی فروشگاه روی سینه {!ov.store.has_logo ? <span className="bc-muted">(لوگویی در «سبکِ برند» ثبت نشده)</span> : null}
            </label>
          </Section>
        ) : null}

        {panel === "face" ? (
          <Section title="چهره" hint="حالتِ چهره را از بالای بوم عوض کنید؛ این‌جا خودِ صورت.">
            <span className="bc-sub">چشم</span>
            <Chips options={choices.eye_style} value={doc.eye_style} disabled={locked} onChange={(v) => setD("eye_style", v)} label="چشم" />
            <span className="bc-sub">ابرو</span>
            <Chips options={choices.brows} value={doc.brows} disabled={locked} onChange={(v) => setD("brows", v)} label="ابرو" />
            <span className="bc-sub">بینی</span>
            <Chips options={choices.nose} value={doc.nose} disabled={locked} onChange={(v) => setD("nose", v)} label="بینی" />
            <span className="bc-sub">جزئیات</span>
            <div className="bc-chips">
              {ov.options.bools.map((b) => <button key={b.key} type="button" className="bc-chip" disabled={locked} aria-pressed={!!doc[b.key as "blush" | "freckles" | "beard"]} onClick={() => setD(b.key as "blush" | "freckles" | "beard", !doc[b.key as "blush" | "freckles" | "beard"])}>{b.fa}</button>)}
            </div>
          </Section>
        ) : null}

        {panel === "hair" ? (
          <Section title="مو، کلاه و عینک">
            <span className="bc-sub">مو</span>
            <Chips options={choices.hair} value={doc.hair} disabled={locked} onChange={(v) => setD("hair", v)} label="مو" />
            <span className="bc-sub">کلاه</span>
            <Chips options={choices.hat} value={doc.hat} disabled={locked} onChange={(v) => setD("hat", v)} label="کلاه" />
            <span className="bc-sub">وسیلهٔ اضافه</span>
            <Chips options={choices.extra} value={doc.extra} disabled={locked} onChange={(v) => setD("extra", v)} label="وسیلهٔ اضافه" />
          </Section>
        ) : null}

        {panel === "outfit" ? (
          <Section title="لباس">
            <span className="bc-sub">بالاتنه</span>
            <Chips options={choices.outfit} value={doc.outfit} disabled={locked} onChange={(v) => setD("outfit", v)} label="بالاتنه" />
            <span className="bc-sub">پایین‌تنه</span>
            <Chips options={choices.bottoms} value={doc.bottoms} disabled={locked} onChange={(v) => setD("bottoms", v)} label="پایین‌تنه" />
            <span className="bc-sub">کفش</span>
            <Chips options={choices.shoes_type} value={doc.shoes_type} disabled={locked} onChange={(v) => setD("shoes_type", v)} label="کفش" />
            <span className="bc-sub">گردن‌آویز</span>
            <Chips options={choices.neck} value={doc.neck} disabled={locked} onChange={(v) => setD("neck", v)} label="گردن‌آویز" />
          </Section>
        ) : null}

        {panel === "prop" ? (
          <Section title="وسیلهٔ دست" hint="در صحنه‌ها می‌شود «خودکار» گذاشت تا ژستِ جمعِ دمبل و بالابردنِ هالتر وسیلهٔ خودشان را بگیرند.">
            <Chips options={choices.prop} value={doc.prop} disabled={locked} onChange={(v) => setD("prop", v)} label="وسیلهٔ دست" />
          </Section>
        ) : null}

        {panel === "colour" ? (
          <Section title="رنگ‌ها" hint="رنگ‌های کیتِ برند زیرِ هر فیلد؛ با یک کلیک می‌نشیند.">
            <div className="bc-fields">
              {colourFields.map(([k, label]) => <ColourField key={k} label={label} value={String(doc[k])} disabled={locked} swatches={swatches} onChange={(v) => setD(k, v as never)} />)}
              {doc.style === "stick" ? (
                <>
                  <ColourField label="دست و پا (آدمک‌چوبی)" value={doc.limb_colour} disabled={locked} swatches={swatches} onChange={(v) => setD("limb_colour", v)} />
                  <ColourField label="سر (آدمک‌چوبی)" value={doc.head_fill} disabled={locked} swatches={swatches} onChange={(v) => setD("head_fill", v)} />
                </>
              ) : null}
            </div>
          </Section>
        ) : null}

        {panel === "layers" ? (
          <Section title="لایه‌ها و شکل‌ها" hint={vector ? `تا ${fa(L.max_layers)} لایه. لایه‌های بالایی روی بدن‌اند و «زیر» پشتِ آن.` : "فقط برای سبک‌های برداری."}>
            <span className="bc-sub">کتابخانهٔ شکل‌ها (از ادیتورِ عکس)</span>
            <div className="bce-shapes">
              {SHAPES.map((s) => {
                const b = buildShape(s.id);
                return (
                  <button key={s.id} type="button" disabled={locked || !vector} aria-pressed={tool === `shape:${s.id}`} title={s.title} onClick={() => { setTool(`shape:${s.id}`); setPen(null); }}>
                    <svg viewBox="-0.05 -0.05 1.1 1.1" aria-hidden>{b ? <polygon points={b.path.pts.map((p) => `${p.x},${p.y}`).join(" ")} /> : null}</svg>
                    {s.title}
                  </button>
                );
              })}
            </div>
            <span className="bc-sub">ترتیبِ لایه‌ها (بالا = جلو)</span>
            <div className="bce-layers" role="listbox" aria-label="لایه‌ها">
              {[...above].reverse().map((l) => <LayerRow key={l.id} l={l} sel={selId === l.id} locked={locked} onSel={() => { setSelId(l.id); setTool("select"); }} onUp={() => moveZ(l.id, 1)} onDown={() => moveZ(l.id, -1)} onHide={() => upd(l.id, { hidden: !l.hidden })} onLock={() => upd(l.id, { locked: !l.locked })} onDel={() => removeLayer(l.id)} />)}
              <div className="bce-layer is-figure"><span /> <span>شخصیت (بدن، لباس، چهره)</span> <span /></div>
              {[...below].reverse().map((l) => <LayerRow key={l.id} l={l} sel={selId === l.id} locked={locked} onSel={() => { setSelId(l.id); setTool("select"); }} onUp={() => moveZ(l.id, 1)} onDown={() => moveZ(l.id, -1)} onHide={() => upd(l.id, { hidden: !l.hidden })} onLock={() => upd(l.id, { locked: !l.locked })} onDel={() => removeLayer(l.id)} />)}
              {!doc.layers.length ? <span className="bc-muted">هنوز لایه‌ای نیست؛ یک ابزار بردارید و روی بوم بکشید.</span> : null}
            </div>
            {sel ? (
              <div className="bce-props" data-testid="layer-props">
                <label className="bc-label wide">نام<Input value={sel.name} maxLength={40} disabled={locked} onChange={(e) => upd(sel.id, { name: e.target.value })} /></label>
                <label className="bc-label">چسبیده به
                  <Select value={sel.anchor} disabled={locked} onChange={(e) => changeAnchor(sel, e.target.value as Anchor)}>{ov.options.anchors.map((a) => <option key={a.key} value={a.key}>{a.fa}</option>)}</Select>
                </label>
                <label className="bc-label">جایگاه
                  <Select value={sel.above ? "above" : "below"} disabled={locked} onChange={(e) => upd(sel.id, { above: e.target.value === "above" })}><option value="above">روی شخصیت</option><option value="below">پشتِ شخصیت</option></Select>
                </label>
                {sel.shape !== "line" ? <ColourField label="پُر" value={sel.fill ?? "#cccccc"} disabled={locked} swatches={swatches} onChange={(v) => upd(sel.id, { fill: v })} /> : null}
                <ColourField label={sel.shape === "line" ? "رنگِ خط" : "خطِ دور"} value={sel.stroke ?? sel.fill ?? "#000000"} disabled={locked} swatches={swatches} onChange={(v) => upd(sel.id, { stroke: v, ...(sel.shape === "line" ? { fill: v } : {}) })} />
                <label className="bc-label">ضخامتِ خط: {fa(sel.sw)}<input type="range" min={0} max={30} step={0.5} value={sel.sw} disabled={locked} onChange={(e) => upd(sel.id, { sw: Number(e.target.value) })} style={{ accentColor: "var(--brand)" }} /></label>
                <label className="bc-label">شفافیت: {fa(Math.round(sel.opacity * 100))}٪<input type="range" min={0.05} max={1} step={0.05} value={sel.opacity} disabled={locked} onChange={(e) => upd(sel.id, { opacity: Number(e.target.value) })} style={{ accentColor: "var(--brand)" }} /></label>
                {sel.shape === "rect" ? <label className="bc-label">گردیِ گوشه: {fa(sel.radius)}<input type="range" min={0} max={80} value={sel.radius} disabled={locked} onChange={(e) => upd(sel.id, { radius: Number(e.target.value) })} style={{ accentColor: "var(--brand)" }} /></label> : null}
                <label className="bc-label">چرخش: {fa(Math.round(sel.box.rot))}°<input type="range" min={-180} max={180} value={sel.box.rot} disabled={locked} onChange={(e) => upd(sel.id, { box: { ...sel.box, rot: Number(e.target.value) } })} style={{ accentColor: "var(--brand)" }} /></label>
                <div className="bc-row wide">
                  <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={() => { const c = { ...sel, id: uid(), link: "", box: { ...sel.box, cx: sel.box.cx + 14, cy: sel.box.cy + 14 }, name: sel.name ? `${sel.name} کپی` : "" }; addLayer(c); }}>تکثیر</Button>
                  <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={() => upd(sel.id, { flip_x: !sel.flip_x })}>آینهٔ افقی</Button>
                  <Button type="button" variant="danger" size="sm" disabled={locked} onClick={() => removeLayer(sel.id)}>حذف</Button>
                </div>
              </div>
            ) : null}
          </Section>
        ) : null}

        <Section title="پیش‌نمایشِ نهایی" hint="همان تصویری که سرور برای پست می‌کشد (با پس‌زمینهٔ برند).">
          <div className={`bc-previewbox${finalPrev ? "" : " busy"}`}>{finalPrev ? <img src={finalPrev} alt="پیش‌نمایشِ نهایی" /> : <Spinner />}</div>
          <div className="bc-qa">
            {ch.palette.map((p) => <span key={p.role + p.hex} className="bc-row" style={{ gap: 4 }}><i className="bc-dot" style={{ background: p.hex }} />{p.name_fa || p.name}</span>)}
          </div>
        </Section>
      </div>
    </div>
  );
}

function LayerRow({ l, sel, locked, onSel, onUp, onDown, onHide, onLock, onDel }: { l: Layer; sel: boolean; locked: boolean; onSel: () => void; onUp: () => void; onDown: () => void; onHide: () => void; onLock: () => void; onDel: () => void }) {
  const icon = l.shape === "rect" ? "▭" : l.shape === "ellipse" ? "◯" : l.shape === "line" ? "／" : "✎";
  return (
    <div className="bce-layer" role="option" aria-selected={sel} onClick={onSel}>
      <span aria-hidden style={{ textAlign: "center", color: l.fill ?? l.stroke ?? "inherit" }}>{icon}</span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", opacity: l.hidden ? 0.45 : 1 }}>{l.name || (l.shape === "path" ? "مسیر" : l.shape === "rect" ? "مستطیل" : l.shape === "ellipse" ? "بیضی" : "خط")} <small className="bc-muted">· {l.anchor === "world" ? "بوم" : l.anchor === "head" ? "سر" : l.anchor === "body" ? "بدن" : "دست"}</small></span>
      <span style={{ whiteSpace: "nowrap" }}>
        <button type="button" aria-label="بالاتر" disabled={locked} onClick={(e) => { e.stopPropagation(); onUp(); }}>▲</button>
        <button type="button" aria-label="پایین‌تر" disabled={locked} onClick={(e) => { e.stopPropagation(); onDown(); }}>▼</button>
        <button type="button" aria-label={l.hidden ? "نشان‌دادن" : "پنهان‌کردن"} onClick={(e) => { e.stopPropagation(); onHide(); }}>{l.hidden ? "◌" : "●"}</button>
        <button type="button" aria-label={l.locked ? "بازکردنِ قفلِ لایه" : "قفلِ لایه"} disabled={locked} onClick={(e) => { e.stopPropagation(); onLock(); }}>{l.locked ? "قفل" : "باز"}</button>
        <button type="button" aria-label="حذفِ لایه" disabled={locked} onClick={(e) => { e.stopPropagation(); onDel(); }}>×</button>
      </span>
    </div>
  );
}
